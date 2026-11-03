# astrbot_plugin_zeroshot_sing

[qqbot-music](https://github.com/aa1805370178-dot/qqbot-music) 的 AstrBot 插件：**让你的 AI 自己学会唱歌**。

给机器人一个 `sing` 工具。有人让它唱歌时：

- 会唱：用你配置的音色唱副歌（或整首），一两分钟后以语音发出来；
- 不会：自己去 QQ 音乐定原唱、到 B 站找对得上的版本、分离人声和伴奏，几分钟后学会，再点一次就能唱；
- 没说唱哪首：从会唱的歌里随机挑，只说了歌手就在这个歌手的歌里挑。

零样本换声，只要一段 10–25 秒的干净录音当音色，不用训练；GTX 1650 Ti 4G 显卡也能跑。

插件本身不跑模型，只通过 HTTP 调 qqbot-music 的唱歌服务，所以**要先装好 qqbot-music**（换声、分离都在那边，需要 NVIDIA 显卡）。

## 安装

1. 按 [qqbot-music 的 README](https://github.com/aa1805370178-dot/qqbot-music#快速开始) 装好，确认 `python -m qqbot_music serve` 能起来。
2. 在 AstrBot 插件市场安装本插件，或者把本仓库克隆到 `data/plugins/` 下。
3. 在 WebUI 的插件配置里填好服务地址；想让插件在服务没开时自动拉起，填 `start_command` 和 `start_cwd`。

## 配置

| 项 | 默认 | 说明 |
|---|---|---|
| `url` | `http://127.0.0.1:8766` | 唱歌服务地址 |
| `start_command` | 空 | 服务没开时用来启动它的命令，例：`D:/xxx/seed-vc/env/Scripts/python.exe -m qqbot_music serve`；留空就要你自己先开服务 |
| `start_cwd` | 空 | 启动命令的工作目录（qqbot-music 目录） |
| `start_seconds` | 120 | 等服务启动的最长秒数 |
| `allow_full` | true | 是否允许唱整首（整首要好几分钟） |
| `chorus_timeout` / `full_timeout` | 1200 / 3600 | 唱副歌 / 整首的超时秒数，从排到这首开始算（服务正在学别的歌时还要等它学完） |

点了几首不同的歌会按顺序排队，一首首唱好发出；工具会告诉模型前面还有几首。同一会话里同一首歌在唱、在排队或刚唱完不到 2 分钟时，重复调用 `sing` 不会再唱一遍——小模型常把一次点歌连调好几次。

实测（AstrBot 4.29.4 + WebChat + 硅基流动 Qwen3-8B，GTX 1650 Ti 4G）：曲库里有的歌点歌后约 1 分钟收到语音；没学过的《晴天》点歌后开始学，约 8 分钟学会，再点一次约 2 分钟收到语音（含拉起服务、加载模型）。

语音以 WAV 发送，QQ（aiocqhttp / NapCat）会自己转码。唱好的文件放在 `data/plugin_data/astrbot_plugin_zeroshot_sing/sung/`，只留最近 20 首。

## 其他框架

- MaiBot：[qqbot-music-maibot](https://github.com/aa1805370178-dot/qqbot-music-maibot)
- DeepSeek Harness（大肥鱼）：[dsh-zeroshot-sing](https://github.com/aa1805370178-dot/dsh-zeroshot-sing)

## 许可证

GPL-3.0-or-later
