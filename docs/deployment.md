# 部署说明

## 1. 树莓派安装

```bash
cd ~/resp_lanu
bash scripts/setup_pi.sh
```

## 2. 准备配置

```bash
cp .env.example .env
```

至少修改：

- `RESP_LANU_ADMIN_TOKEN`
- `RESP_LANU_SESSION_SECRET`

监听 `0.0.0.0` 或其他非回环地址时，服务会拒绝使用内置默认管理令牌或默认 session secret 启动。`.env.example` 中的 `change-me` 也只是占位值，上线前必须替换成部署专用值。

如果要启用兼容 OpenAI 的对话接口，再补：

- `RESP_LANU_OPENAI_BASE_URL`
- `RESP_LANU_OPENAI_API_KEY`
- `RESP_LANU_OPENAI_MODEL`

## 3. 启动服务

```bash
source .venv/bin/activate
RESP_LANU_PROFILE=pi-offline resp-lanu-serve --profile pi-offline --host 0.0.0.0 --port 8000
```

## 4. 浏览器访问

```text
http://<raspberry-pi-ip>:8000
```

## 5. 注册 systemd

复制模板：

```bash
sudo install -d -m 0750 /etc/resp-lanu
sudo cp .env.example /etc/resp-lanu/resp-lanu.env
sudo nano /etc/resp-lanu/resp-lanu.env
sudo cp deploy/resp-lanu.service /etc/systemd/system/resp-lanu.service
sudo systemctl daemon-reload
sudo systemctl enable --now resp-lanu.service
```

查看状态：

```bash
sudo systemctl status resp-lanu.service
```

## 6. 手工验收清单

1. `resp-lanu-doctor --profile pi-offline` 输出健康信息。
2. `/health/live` 返回 200。
3. 浏览器能打开 `/login` 并成功登录。
4. 上传一个 WAV 后能完成一轮任务。
5. 浏览器录音后也能完成一轮任务，且 `Artifacts` 里能看到原始上传音频和必要时的 `converted_audio`。
6. `History` 页能看到会话和 turn。
7. `Artifacts` 页能下载 `asr_result.json` 和回复音频。
8. `resp-lanu-export-legacy-artifacts` 能导出旧版实验目录。
