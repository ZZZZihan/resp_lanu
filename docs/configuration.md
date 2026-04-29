# 配置说明

项目通过 `.env` 和环境变量统一配置，前缀固定为 `RESP_LANU_`。

## 常用字段

| 变量 | 作用 |
| --- | --- |
| `RESP_LANU_PROFILE` | `dev-mac` / `pi-offline` / `pi-connected` |
| `RESP_LANU_BIND_HOST` | 服务监听地址 |
| `RESP_LANU_BIND_PORT` | 服务监听端口 |
| `RESP_LANU_ADMIN_TOKEN` | 浏览器控制台管理令牌 |
| `RESP_LANU_SESSION_SECRET` | Session 中间件密钥 |
| `RESP_LANU_MODEL_DIR` | Vosk 模型目录 |
| `RESP_LANU_DIALOGUE_PROVIDER` | `rule-based` / `openai-compatible` / `zeroclaw` / `mimo-router` |
| `RESP_LANU_TTS_PROVIDER` | `espeak` / `piper` / `edge-tts` / `none` |
| `RESP_LANU_ENABLE_TTS` | 是否启用 TTS |
| `RESP_LANU_RECORDING_DEVICE` | Pi 本机录音设备；留空时用 `arecord -l` 自动选择第一个设备 |
| `RESP_LANU_PLAY_ASSISTANT_AUDIO_ON_SERVER` | 是否在服务端播放助手语音回复，适合 Pi5 蓝牙音响实验 |
| `RESP_LANU_EDGE_TTS_VOICE` | `edge-tts` 语音，默认 `zh-CN-XiaoxiaoNeural` |
| `RESP_LANU_AUDIO_PLAYER_BINARY` | 服务端播放命令，Pi5 蓝牙音响推荐 `pw-play` |
| `RESP_LANU_AUDIO_PLAYER_ARGS` | 服务端播放命令参数；Pi5 HDMI1 可用 `-D plughw:CARD=vc4hdmi1,DEV=0` |
| `RESP_LANU_MAX_UPLOAD_BYTES` | 单个音频上传最大字节数，默认 `26214400` |
| `RESP_LANU_GENERATE_FEATURE_ARTIFACTS` | 是否在 Web/runtime 主路径生成 `features/` 调试产物，默认 `false` |
| `RESP_LANU_OPENAI_BASE_URL` | OpenAI-compatible 接口地址 |
| `RESP_LANU_OPENAI_API_KEY` | 对话 API key |
| `RESP_LANU_OPENAI_MODEL` | 对话模型名 |
| `RESP_LANU_ZEROCLAW_BINARY` | ZeroClaw 可执行文件路径，使用 `zeroclaw` provider 时需要 |
| `RESP_LANU_ZEROCLAW_WORKING_DIR` | ZeroClaw 工作目录，通常是 ZeroClaw 仓库或安装目录 |
| `RESP_LANU_ZEROCLAW_PROVIDER` | 传给 `zeroclaw agent --provider` 的 provider，例如 `custom:https://.../v1` |
| `RESP_LANU_ZEROCLAW_MODEL` | 传给 `zeroclaw agent --model` 的模型名 |
| `RESP_LANU_ZEROCLAW_API_KEY` | 传给 ZeroClaw 的通用 API key，会注入 `API_KEY` / `ZEROCLAW_API_KEY` / `OPENAI_API_KEY` |
| `RESP_LANU_ZEROCLAW_TIMEOUT_SECONDS` | ZeroClaw 单轮对话超时时间，默认 `90` |
| `RESP_LANU_PIPER_MODEL_PATH` | Piper 模型路径 |

## 对话 Provider

- `rule-based`：内置离线规则回复，适合无外部依赖的演示。
- `openai-compatible`：resp-lanu 直接调用兼容 OpenAI Chat Completions 的服务。
- `zeroclaw`：resp-lanu 只负责语音入口、ASR、历史和产物，识别后的文本交给 `zeroclaw agent`；适合把 ZeroClaw 作为统一对话与行动入口。
- `mimo-router`：普通中文对话走 MiMo；工具、记忆、agent、硬件/机器人动作和长期 daemon 请求走 ZeroClaw。路由结果会记录在任务 metadata 的 `route`、`dialogue_provider` 和 `intent_reason`，不会记录 API key。

Pi5 connected 模式推荐：

```dotenv
RESP_LANU_PROFILE=pi-connected
RESP_LANU_DIALOGUE_PROVIDER=mimo-router
RESP_LANU_OPENAI_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
RESP_LANU_OPENAI_API_KEY=<mimokey>
RESP_LANU_OPENAI_MODEL=mimo-v2.5
RESP_LANU_ZEROCLAW_BINARY=/home/pi/zeroclaw/zeroclaw
RESP_LANU_ZEROCLAW_WORKING_DIR=/home/pi/zeroclaw
RESP_LANU_ZEROCLAW_PROVIDER=custom:https://token-plan-cn.xiaomimimo.com/v1
RESP_LANU_ZEROCLAW_MODEL=mimo-v2.5
RESP_LANU_ZEROCLAW_API_KEY=<mimokey>
RESP_LANU_ZEROCLAW_TIMEOUT_SECONDS=90
RESP_LANU_RECORDING_DEVICE=plughw:CARD=Device,DEV=0
RESP_LANU_TTS_PROVIDER=edge-tts
RESP_LANU_ENABLE_TTS=true
RESP_LANU_PLAY_ASSISTANT_AUDIO_ON_SERVER=true
RESP_LANU_AUDIO_PLAYER_BINARY=pw-play
```

Web 控制台里的“Pi5 录音并提交”按钮会调用服务端 `/api/v1/audio/record`，因此使用的是树莓派本机麦克风，不依赖浏览器麦克风权限。开启服务端播放后，生成的助手语音会通过 Pi5 当前默认音频输出播放，例如已连接的蓝牙音响。

如果使用 HDMI 音频而不是蓝牙，Pi5 的第二个 HDMI 输出常见配置如下；`edge-tts` 生成的 MP3 会自动转换成 48kHz 双声道 WAV 后交给 `aplay`：

```dotenv
RESP_LANU_AUDIO_PLAYER_BINARY=aplay
RESP_LANU_AUDIO_PLAYER_ARGS=-D plughw:CARD=vc4hdmi1,DEV=0
```

## Profile 含义

### `dev-mac`

- 监听 `127.0.0.1`
- 适合本机调试
- 但如果显式设置 `RESP_LANU_BIND_HOST` 或传 `--host`，会保留你的配置，不会被 profile 覆盖

### `pi-offline`

- 监听 `0.0.0.0`
- 默认规则对话
- 默认本地 TTS
- 如果显式设置 `RESP_LANU_BIND_HOST`，会优先使用你的自定义监听地址
- 局域网监听时必须设置非默认 `RESP_LANU_ADMIN_TOKEN` 和 `RESP_LANU_SESSION_SECRET`

### `pi-connected`

- 监听 `0.0.0.0`
- 优先尝试兼容 OpenAI 的对话接口
- 若未配置外部对话接口，会回退到本地规则回复
- 如果显式设置 `RESP_LANU_BIND_HOST`，会优先使用你的自定义监听地址
- 局域网监听时必须设置非默认 `RESP_LANU_ADMIN_TOKEN` 和 `RESP_LANU_SESSION_SECRET`
