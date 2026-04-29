# resp-lanu

一个面向 Raspberry Pi 5 的离线优先语音助手项目。它把原来的实验型 ASR 脚本重构成了单节点本地服务：树莓派运行 FastAPI 进程，Mac 或浏览器访问 Web 控制台，底层仍复用现有的音频预处理、特征提取、Vosk 识别和短语纠正链路。

## 现在的项目形态

- 本地 HTTP 服务：FastAPI + Jinja2 + SSE
- 离线优先：默认本地识别、本地规则对话、本地 TTS
- 浏览器控制台：`Assistant / History / Artifacts / Settings / Health`
- 单 worker 任务流：`ingest -> preprocess -> asr -> dialogue -> tts -> persist`
- 存储模型：SQLite 元数据 + `data/sessions/<session>/<turn>/` 产物目录
- 兼容旧实验输出：仍可导出 `artifacts/<run_tag>/` 风格结果

## 核心能力

- 上传音频、浏览器录音，或直接调用 Pi5 本机 USB 麦克风录音并创建会话任务
- 自动保存预处理摘要、ASR 结果和回复音频；特征摘要可按需开启
- 规则型离线对话默认可用
- 配置了兼容 OpenAI 的接口后，对话能力自动升级
- 可用 `mimo-router` 把普通中文对话交给 MiMo，把工具、记忆、agent、硬件/机器人动作和长期 daemon 请求交给 ZeroClaw
- `espeak-ng` 默认做本地 TTS，可切换到 Piper 或 `edge-tts`，并可在 Pi5 默认音频输出播放回复
- Legacy CLI/Tk 入口保留，但主路径已经切到 Web 控制台

## 快速开始

### 1. 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install ".[dev,assistant]"
cp .env.example .env
resp-lanu-serve --profile dev-mac --host 127.0.0.1 --port 8000
```

打开浏览器访问：

```text
http://127.0.0.1:8000
```

默认管理令牌见 `.env.example`，建议首次启动后立即修改。监听局域网地址时必须设置非默认 `RESP_LANU_ADMIN_TOKEN` 和 `RESP_LANU_SESSION_SECRET`，否则服务会拒绝启动。

### 2. 在树莓派上安装

```bash
bash scripts/setup_pi.sh
```

### 3. 在树莓派上启动服务

```bash
bash scripts/run_server.sh pi-offline
```

或直接使用 console script：

```bash
RESP_LANU_PROFILE=pi-offline resp-lanu-serve --profile pi-offline --host 0.0.0.0 --port 8000
```

局域网启动前请先复制 `.env.example` 并替换管理令牌和 session secret。

## 目录结构

```text
resp_lanu/
├── pyproject.toml
├── src/resp_lanu/
│   ├── audio.py
│   ├── asr.py
│   ├── cli.py
│   ├── features.py
│   ├── gui.py
│   ├── legacy.py
│   ├── pipeline.py
│   ├── providers.py
│   ├── runtime.py
│   ├── schemas.py
│   ├── settings.py
│   ├── storage.py
│   ├── web.py
│   ├── static/
│   └── templates/
├── scripts/
├── tests/
├── docs/
└── deploy/
```

## 主要入口

- `resp-lanu-serve`：启动本地 HTTP 服务
- `resp-lanu-doctor`：检查配置和 provider 状态
- `resp-lanu-voice-turn`：Pi5 本机录音、对话、TTS 播放的一轮或循环语音对话
- `resp-lanu-export-legacy-artifacts`：把最新完成任务导出成旧版 `artifacts/` 布局
- `scripts/run_pipeline.sh`：旧实验链路壳层
- `scripts/dialog_window.py`：Legacy Tk 窗口

## API 概览

服务主路由固定为 `/api/v1`，主要资源包括：

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/health`
- `GET /api/v1/settings`
- `GET /api/v1/sessions`
- `GET /api/v1/turns/{turn_id}`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/events`
- `GET /api/v1/artifacts`
- `POST /api/v1/audio/upload`
- `POST /api/v1/audio/record`
- `GET /api/v1/audio/recordings`
- `POST /api/v1/assistant/respond`

## 配置

项目使用 `pydantic-settings` 统一读取 `.env` 和环境变量，常用变量见 [`.env.example`](.env.example)。

支持的 profile：

- `dev-mac`
- `pi-offline`
- `pi-connected`

## 树莓派部署

- systemd 模板： [deploy/resp-lanu.service](deploy/resp-lanu.service)
- 快速上手： [docs/raspberry_pi_quickstart.md](docs/raspberry_pi_quickstart.md)
- 部署说明： [docs/deployment.md](docs/deployment.md)
- 配置说明： [docs/configuration.md](docs/configuration.md)

## 架构文档

- [docs/architecture.md](docs/architecture.md)
- [docs/adr/0001-local-service-architecture.md](docs/adr/0001-local-service-architecture.md)
- [docs/experiment_process.md](docs/experiment_process.md)
- [docs/pi5_run_log.md](docs/pi5_run_log.md)

## 测试与质量门禁

```bash
ruff check .
python -m pytest
python -m compileall src scripts tests
```

测试覆盖：

- 音频预处理与特征提取回归
- phrase hints / grammar 配置校验
- 任务状态流转
- provider fallback
- FastAPI API、上传、SSE 和历史查询
- legacy artifact 导出

Web/runtime 主路径默认不生成 `features/` 调试目录；需要课程实验或性能分析时可设置 `RESP_LANU_GENERATE_FEATURE_ARTIFACTS=true`。

## 当前默认 provider

- 识别：`VoskRecognizer`
- 对话：`RuleBasedDialogueEngine`
- TTS：`EspeakSynthesizer`

可选 provider：

- `OpenAICompatibleDialogueEngine`
- `ZeroClawDialogueEngine`
- `MimoRouterDialogueEngine`
- `PiperSynthesizer`
- `EdgeTtsSynthesizer`

## 已知边界

- 一期仍然是单节点本地系统，不做多用户和公网暴露
- `Browser Use` 没有被做成项目运行时依赖
- Legacy Tk 窗口仍保留，但不再是主交互面
