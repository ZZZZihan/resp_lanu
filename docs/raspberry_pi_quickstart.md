# 树莓派快速上手

这份文档专门对应新的本地服务形态：树莓派运行 HTTP 服务，你在浏览器里打开控制台使用语音助手。

## 1. 环境要求

- Raspberry Pi 5
- Debian / Raspberry Pi OS
- 已能通过 SSH 进入树莓派
- 可选：USB 麦克风
- 可选：扬声器或耳机，用于播放 TTS

## 2. 同步项目

```bash
rsync -av --delete \
  --exclude .venv \
  --exclude data \
  --exclude artifacts \
  --exclude models \
  ./ pi5:~/resp_lanu/
```

## 3. 安装项目

```bash
ssh pi5 'cd ~/resp_lanu && bash scripts/setup_pi.sh'
```

安装脚本会：

- 创建 `.venv`
- 安装项目本身和 `pi` 依赖组
- 下载 Vosk 中文小模型
- 安装 `ffmpeg`、`alsa-utils`、`python3-tk`、`espeak-ng`

## 4. 配置 `.env`

```bash
ssh pi5 'cd ~/resp_lanu && cp .env.example .env'
```

建议至少修改：

- `RESP_LANU_ADMIN_TOKEN`
- `RESP_LANU_SESSION_SECRET`

## 5. 启动服务

```bash
ssh pi5 'cd ~/resp_lanu && bash scripts/run_server.sh pi-offline'
```

## 6. 浏览器访问

在 Mac 上打开：

```text
http://<pi-ip>:8000
```

登录后主页面就是 `Assistant` 控制台。

## 7. 浏览器里的典型流程

1. 登录控制台。
2. 选择已有 session 或创建新 session。
3. 输入文本，上传 WAV，或者点击“开始录音”直接在浏览器里录音。
4. 提交任务。
5. 浏览器录音会先上传为 `webm/ogg/mp4` 之类格式，后端会用 `ffmpeg` 自动转成 WAV 再送进 ASR。
6. 查看状态流转、识别文本、助手回复和回复音频。
7. 到 `History` 和 `Artifacts` 页回看结果。

## 8. Legacy 实验链路

如果你仍然要做课程实验展示，可以继续使用：

```bash
bash scripts/run_pipeline.sh sample_audio/demo_cn.wav demo_cn_pi5
```

或导出新的会话结果为旧版目录：

```bash
resp-lanu-export-legacy-artifacts --output-dir artifacts/legacy_demo
```

## 9. 常见问题

### 浏览器打不开

先检查：

```bash
resp-lanu-doctor --profile pi-offline
```

以及：

```bash
curl http://127.0.0.1:8000/health/live
```

### 没有录音设备

```bash
arecord -l
```

### 没有声音输出

检查 `espeak-ng` 是否已安装，并确认扬声器输出设备可用。

### 浏览器录音后无法识别

先检查 `ffmpeg` 是否存在，因为浏览器录音默认不是 WAV，后端会先做格式转换：

```bash
ffmpeg -version
```
