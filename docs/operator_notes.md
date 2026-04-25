# resp-lanu 运维速查

这份文档用于记录本地开发、树莓派部署和 Web 控制台登录时最常用的信息。

不要把真实生产密码、API key 或长期有效 token 写进仓库。真实值建议只放在部署机器的 `.env`、密码管理器或离线记录里。

## Web 控制台登录

| 项目 | 本地开发默认值 | 说明 |
| --- | --- | --- |
| 登录地址 | `http://127.0.0.1:8000/login` | 默认 `dev-mac` 本地服务地址 |
| 账号 | 无账号字段 | 当前只使用管理令牌登录 |
| 管理令牌 | `resp-lanu-admin` | 仅限本地开发默认值 |
| Session secret | `resp-lanu-session-secret` | 仅限本地开发默认值，不需要在页面输入 |

局域网或树莓派部署时不要使用上面的默认令牌。服务监听 `0.0.0.0` 等非回环地址时，如果仍使用默认管理令牌或默认 session secret，会拒绝启动。

## 生产/局域网需要替换的敏感项

在部署机器的 `.env` 中设置：

```dotenv
RESP_LANU_ADMIN_TOKEN=<替换成部署专用管理令牌>
RESP_LANU_SESSION_SECRET=<替换成部署专用 session secret>
```

如果启用 OpenAI-compatible 对话接口，再设置：

```dotenv
RESP_LANU_OPENAI_BASE_URL=<接口地址>
RESP_LANU_OPENAI_API_KEY=<接口密钥>
RESP_LANU_OPENAI_MODEL=<模型名>
```

## 常用启动命令

本机开发：

```bash
resp-lanu-serve --profile dev-mac --host 127.0.0.1 --port 8000
```

树莓派/LAN：

```bash
RESP_LANU_PROFILE=pi-offline resp-lanu-serve --profile pi-offline --host 0.0.0.0 --port 8000
```

配置检查：

```bash
resp-lanu-doctor --profile dev-mac
```

## 重要路径

| 路径 | 用途 |
| --- | --- |
| `.env.example` | 环境变量模板 |
| `docs/configuration.md` | 完整配置说明 |
| `docs/deployment.md` | 部署说明 |
| `docs/raspberry_pi_quickstart.md` | 树莓派快速启动 |
| `data/resp_lanu.db` | 默认 SQLite 数据库 |
| `data/uploads/` | 上传音频 |
| `data/sessions/` | 会话运行产物 |
| `models/vosk-model-small-cn-0.22/` | 默认 Vosk 模型目录 |
| `sample_audio/demo_cn.wav` | 本地演示音频 |
| `sample_audio/demo_cn_phrase_hints.json` | 默认短语纠错提示 |

## API 调试提示

浏览器登录后可以直接使用控制台页面。脚本或 curl 调 API 时，用 `x-admin-token` 请求头传管理令牌：

```bash
curl -H "x-admin-token: <管理令牌>" http://127.0.0.1:8000/api/v1/health
```

常用接口：

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/health` | 服务健康状态 |
| `GET /api/v1/settings` | 当前配置和 provider 状态 |
| `GET /api/v1/sessions` | 会话列表 |
| `GET /api/v1/artifacts` | 产物列表 |
| `POST /api/v1/audio/upload` | 上传音频 |
| `POST /api/v1/assistant/respond` | 提交助手任务 |

## 维护提醒

- Web 控制台是本地/LAN 管理面，不要暴露到公网。
- 修改 `.env` 后重启服务才会生效。
- 需要课程实验特征产物时才开启 `RESP_LANU_GENERATE_FEATURE_ARTIFACTS=true`。
- macOS 打包复制到 Linux 后如果出现 `._*` AppleDouble 文件，可在远端执行 `find . -name "._*" -delete` 清理。
- 树莓派主机别名记录：`pi5`，Debian 13，Python 3.13.5，4 GB RAM。
