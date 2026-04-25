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
| `RESP_LANU_DIALOGUE_PROVIDER` | `rule-based` 或 `openai-compatible` |
| `RESP_LANU_TTS_PROVIDER` | `espeak` / `piper` / `none` |
| `RESP_LANU_ENABLE_TTS` | 是否启用 TTS |
| `RESP_LANU_MAX_UPLOAD_BYTES` | 单个音频上传最大字节数，默认 `26214400` |
| `RESP_LANU_GENERATE_FEATURE_ARTIFACTS` | 是否在 Web/runtime 主路径生成 `features/` 调试产物，默认 `false` |
| `RESP_LANU_OPENAI_BASE_URL` | OpenAI-compatible 接口地址 |
| `RESP_LANU_OPENAI_API_KEY` | 对话 API key |
| `RESP_LANU_OPENAI_MODEL` | 对话模型名 |
| `RESP_LANU_PIPER_MODEL_PATH` | Piper 模型路径 |

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
