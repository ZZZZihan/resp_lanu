# 树莓派 5 SSH 实验运行记录

## 1. 远端环境

- 主机别名：`pi5`
- 系统：Debian 13 (trixie)
- 内核：`6.12.75+rpt-rpi-2712`
- Python：`3.13.5`
- 内存：4 GB
- 可用磁盘：约 12 GB

检查结果里没有发现录音设备，所以本次先用仓库内置的中文示例音频 `sample_audio/demo_cn.wav` 跑通全链路。

## 2. 执行命令

```bash
tar czf - --exclude='.venv' --exclude='artifacts' --exclude='models' . | ssh pi5 'cd ~/resp_lanu && tar xzf -'
ssh pi5 'cd ~/resp_lanu && bash scripts/setup_pi.sh'
ssh pi5 'cd ~/resp_lanu && bash scripts/run_pipeline.sh sample_audio/demo_cn.wav demo_cn_pi5'
ssh pi5 'cd ~/resp_lanu && bash scripts/run_pipeline.sh sample_audio/demo_cn.wav demo_cn_grammar_v2 "" sample_audio/demo_cn_grammar.json'
```

## 3. 默认解码结果

输出目录：`artifacts/demo_cn_pi5/`

预处理摘要：

- 采样率：`16000 Hz`
- 时长：`7.6689 s`
- 峰值归一化后：`0.95`
- RMS：`0.099108`

特征摘要：

- `MFCC`: `766 x 13`
- `Delta`: `766 x 13`
- `Delta-Delta`: `766 x 13`
- `Filter Bank`: `766 x 26`
- `voiced_frame_ratio`: `0.699346`

识别文本：

```text
你好 今天 我们 在 数 没 派 五 上 测试 中文 语音 识别 系统 语音识别 实验 已经 开始
```

原始参考文本：

```text
你好，今天我们在树莓派五上测试中文语音识别系统。语音识别实验已经开始。
```

观察：

- 整体句意正确。
- “树莓派” 被识别成了 “数 没 派”，说明小模型在专有词和合成语音条件下仍然会出现词汇级混淆。
- 其余大部分词语识别正常，证明这套离线实验链路在树莓派 5 上已经可用。

## 4. 受限语法解码结果

输出目录：`artifacts/demo_cn_grammar_v2/`

识别文本：

```text
你好 今天 我们 在 数 没 派 五 上 测试 中文 语音 识别 系统 语音识别 实验 已经 开始
```

观察：

- 这次没有继续退化成 `[unk]`，说明把语法表改成空格分词的 token 序列后，约束搜索生效了。
- 但日志里仍提示 `莓` 不在模型词表里，所以它没法真正把“树莓派”纠正回来。
- 这正好对应课程里的“语言模型和搜索算法”要点：搜索只能在**词表和图**允许的空间里找最优路径，不能凭空创造词。

## 5. 短语提示后处理改进

输出目录：`artifacts/demo_cn_hints/`

执行命令：

```bash
ssh pi5 'cd ~/resp_lanu && bash scripts/run_pipeline.sh sample_audio/demo_cn.wav demo_cn_hints "" "" sample_audio/demo_cn_phrase_hints.json'
```

原始解码文本：

```text
你好 今天 我们 在 数 没 派 五 上 测试 中文 语音 识别 系统 语音识别 实验 已经 开始
```

后处理后的最终文本：

```text
你好 今天 我们 在 树莓派五 上 测试 中文语音识别系统 语音识别实验 已经 开始
```

自动修正记录：

- `数 没 派 五 -> 树莓派五`，平均置信度约 `0.707428`
- `中文 语音 识别 系统 -> 中文语音识别系统`
- `语音识别 实验 -> 语音识别实验`

观察：

- 这一步没有改动声学模型本身，而是在解码后增加了一个轻量的“短语提示”纠正层。
- 对于模型词表里不稳定、但业务上很重要的词组，这种方法比单纯加 grammar 更实用，因为它允许把已知别名映射回标准写法。
- 这也说明当前最稳妥的优化路径不是“强行让小模型学会新词”，而是“保留原始解码 + 增加可审计的领域词后处理”。

## 6. 结论

这次 SSH 实验已经在树莓派 5 上完整跑通了：

1. 环境准备成功。
2. 中文小模型下载成功。
3. 音频预处理成功。
4. MFCC / Delta / Filter Bank 特征提取成功。
5. Vosk 离线解码成功。
6. 结果与中间产物已回传到本地 `artifacts/` 目录。
7. 短语提示后处理已经验证能把 “数 没 派 五” 稳定修正成 “树莓派五”。

下一步最值得做的是接一个 USB 麦克风，再把 `scripts/record_audio.sh` 纳入同样的流程，完成“实时录音 -> 预处理 -> 识别”的现场实验。
