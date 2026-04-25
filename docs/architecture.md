# 架构说明

## 目标

把原来的实验型离线语音识别仓库重构成一个可部署、可追踪、可扩展的本地语音助手系统。

## 系统边界

- 部署边界：单台 Raspberry Pi 5
- 访问边界：局域网浏览器 / Mac 浏览器
- 计算边界：本地单进程 FastAPI + 单 worker
- 存储边界：SQLite + 本地文件系统

## 核心分层

### 1. Domain / DSP

- `audio.py`
- `features.py`
- `asr.py`

这层保留原有音频预处理、MFCC/Filter Bank 特征提取和短语纠正逻辑。

### 2. Providers

- `VoskRecognizer`
- `RuleBasedDialogueEngine`
- `OpenAICompatibleDialogueEngine`
- `EspeakSynthesizer`
- `PiperSynthesizer`

所有外部能力都通过 provider 接口抽象，运行时按配置装配。

### 3. Runtime / Orchestration

- `runtime.py`
- `storage.py`

这层负责任务排队、worker 执行、阶段流转、事件广播、SQLite 持久化和文件产物落盘。

### 4. Delivery

- `web.py`
- `cli.py`
- `templates/`
- `static/`

这层负责 HTTP API、Web 控制台、SSE 推送、登录与 console scripts。

## 任务流

```text
ingest -> preprocess -> asr -> dialogue -> tts -> persist
```

每一步都会更新：

- `jobs.status`
- `jobs.phase`
- `turns.status`
- SSE 事件流
- 必要的 JSON / WAV / 特征文件产物

## 存储模型

### SQLite

- `sessions`
- `turns`
- `jobs`
- `messages`
- `artifacts`
- `settings_snapshots`

### 文件系统

```text
data/
├── resp_lanu.db
├── uploads/
└── sessions/<session_id>/<turn_id>/
    ├── input.wav
    ├── preprocessed.wav
    ├── preprocess_summary.json
    ├── asr_result.json
    ├── assistant_response.json
    ├── assistant_response.wav
    └── features/
```

## 兼容策略

- 旧 `scripts/run_pipeline.sh` 继续保留
- 旧 Tk 窗口继续保留为 legacy
- 新系统支持导出旧版 `artifacts/` 目录结构，方便课程展示和旧材料复用
