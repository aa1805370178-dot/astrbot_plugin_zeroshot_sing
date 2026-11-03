"""qqbot-music 的 AstrBot 插件：给机器人一个 sing 工具，用你配置的音色唱歌、发语音。

插件本身不跑模型，只通过 HTTP 调 qqbot-music 的唱歌服务（python -m qqbot_music serve）。
服务没开时，如果配置了 start_command，就用它拉起来；没配置就告诉模型唱不了。
唱歌要一两分钟，工具先返回「在唱了」，唱好后在后台把语音发到同一个会话。
"""

import asyncio
import shlex
import subprocess
import time
import uuid
from pathlib import Path

import aiohttp

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools, register

PLUGIN_NAME = "astrbot_plugin_zeroshot_sing"

RECENT = 120  # 唱完后多少秒内同一会话再点这首算重复调用


@register(PLUGIN_NAME, "小小墨", "用你配置的音色唱歌、发语音；不会的歌自己去学", "1.0.0")
class QQBotMusicPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._starting = asyncio.Lock()
        # (会话, 歌) → 正在唱、排队或刚唱完（留 RECENT 秒）的后台任务。小模型常把同一次点歌连调好几次（还会自己改成整首），
        # 有缓存的歌一秒就唱完，只挡在唱的挡不住后面那几次，会唱好几遍、发好几条
        self._tasks: dict[tuple[str, str], asyncio.Task] = {}
        # 不同的歌按点歌顺序一首首交给服务（asyncio.Lock 先来先得），超时从轮到这首才开始算
        self._queue = asyncio.Lock()
        self._out = Path(StarTools.get_data_dir(PLUGIN_NAME)) / "sung"
        self._out.mkdir(parents=True, exist_ok=True)

    async def terminate(self):
        for t in self._tasks.values():
            t.cancel()

    # ── 服务 ──────────────────────────────────────────

    @property
    def _url(self) -> str:
        return str(self.config.get("url", "http://127.0.0.1:8766")).rstrip("/")

    async def _alive(self, s: aiohttp.ClientSession) -> bool:
        try:
            async with s.get(f"{self._url}/ping", timeout=aiohttp.ClientTimeout(total=3)) as r:
                return r.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def _ensure(self, s: aiohttp.ClientSession) -> None:
        async with self._starting:
            if await self._alive(s):
                return
            cmd = str(self.config.get("start_command", "")).strip()
            if not cmd:
                raise RuntimeError("唱歌服务没开")
            # 独立进程：机器人重启不带走它，闲置了它自己退
            subprocess.Popen(shlex.split(cmd, posix=False), cwd=self.config.get("start_cwd") or None,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            deadline = time.time() + int(self.config.get("start_seconds", 120))
            while time.time() < deadline:
                await asyncio.sleep(3)
                if await self._alive(s):
                    return
            raise RuntimeError("唱歌服务没起来")

    async def _json(self, method: str, path: str, **kw) -> dict:
        async with aiohttp.ClientSession(trust_env=False) as s:
            await self._ensure(s)
            async with s.request(method, f"{self._url}{path}", timeout=aiohttp.ClientTimeout(total=15), **kw) as r:
                data = await r.json(content_type=None)
        if not isinstance(data, dict):
            raise RuntimeError("唱歌服务返回的不是 JSON 对象")
        return data

    async def _audio(self, sid: str, full: bool) -> bytes:
        timeout = int(self.config.get("full_timeout" if full else "chorus_timeout", 3600 if full else 1200))
        async with aiohttp.ClientSession(trust_env=False) as s:
            await self._ensure(s)
            async with s.post(f"{self._url}/sing", json={"id": sid, "full": full},
                              timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status != 200:
                    raise RuntimeError((await r.text())[:120])
                return await r.read()

    # ── 工具 ──────────────────────────────────────────

    @filter.llm_tool(name="sing")
    async def sing(self, event: AstrMessageEvent, title: str = "", artist: str = "", full: bool = False) -> str:
        """用你自己的声音唱歌，发一条唱歌的语音。只有别人明确要你唱歌时才用，平时聊天不要主动唱。默认只唱副歌；对方明确要整首才把 full 设成 true。对方没指定唱哪首时 title 留空，会从你会唱的歌里随机挑；只说了歌手就填 artist、title 留空。不会的歌会先去学，学的时候告诉对方要等几分钟，学会了再让对方点一次。会不会唱只有调用这个工具才知道，不要凭聊天记录里自己说过的话判断。歌名你没听过也原样填，不要自己改成别的歌。

        Args:
            title(string): 歌名，不带书名号；没指定就留空
            artist(string): 歌手，对方说了才填
            full(boolean): 对方明确要整首时为 true
        """
        title = (title or "").strip().strip("《》「」\"'")
        artist = (artist or "").strip()
        full = full is True and bool(self.config.get("allow_full", True))
        try:
            if title:
                found = await self._json("GET", "/find", params={"title": title, "artist": artist})
                if found.get("status") in ("unknown", "failed"):
                    found = await self._json("POST", "/learn", json={"title": title, "artist": artist})
            else:
                found = await self._json("GET", "/random", params={"artist": artist})
        except Exception as ex:  # 服务问题告诉模型，让它自己跟对方说
            return f"现在唱不了：{ex}"
        status = found.get("status")
        if status == "learning":
            return f"你还不会唱「{title}」，已经在学了，要几分钟，学会后对方再点一次就能唱。"
        if status == "failed":
            return f"「{title}」学不会：{found.get('error', '')}"
        sid = found.get("id")
        if status != "ready" or not sid:
            return "你会唱的歌里没有符合要求的。" if not title else f"你不会唱「{title}」。"
        name = found.get("title") or title
        singer = found.get("artist") or artist
        key = (event.unified_msg_origin, str(sid))
        if key in self._tasks:
            if self._tasks[key].done():
                return f"《{name}》刚唱完，语音已经发到这个会话了，这次不用再唱。"
            return f"《{name}》这次点歌已经在唱或在排队了，唱好会自动发语音，这次不用再唱，跟对方说稍等就行。"
        ahead = sum(not t.done() for t in self._tasks.values())
        task = asyncio.create_task(self._sing_and_send(str(sid), full, event.unified_msg_origin))
        self._tasks[key] = task
        task.add_done_callback(lambda _: asyncio.get_running_loop().call_later(RECENT, self._tasks.pop, key, None))
        lyrics = "／".join(found.get("lyrics") or [])
        what = f"《{name}》{f'（{singer}）' if singer else ''}{'整首' if full else '副歌'}"
        start = f"排上队了：{what}前面还有 {ahead} 首，轮到后" if ahead else f"开始唱{what}，"
        return (f"{start}唱好会自动把语音发到这个会话，你不用也不要自己发语音或文件，回一句话让对方稍等就行。{'副歌歌词：' + lyrics if lyrics and not full else ''}")

    async def _sing_and_send(self, sid: str, full: bool, umo: str) -> None:
        try:
            path = self._out / f"{uuid.uuid4().hex}.wav"
            async with self._queue:
                audio = await self._audio(sid, full)
            path.write_bytes(audio)
            await self.context.send_message(umo, MessageChain([Comp.Record.fromFileSystem(str(path))]))
            self._cleanup()
        except Exception as ex:
            logger.warning(f"[qqbot-music] 没唱出来：{type(ex).__name__} {ex}")
            await self.context.send_message(umo, MessageChain().message(f"（没唱出来：{type(ex).__name__} {ex}）"[:150]))

    def _cleanup(self, keep: int = 20) -> None:
        """只留最近几首，唱过的结果服务那边有缓存，这里不用攒。"""
        files = sorted(self._out.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[keep:]:
            p.unlink(missing_ok=True)
