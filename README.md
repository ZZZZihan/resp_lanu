# 树莓派 5 语音识别实验

这个仓库给出一个可以通过 SSH 在树莓派 5 上跑通的最小离线语音识别实验。它既覆盖课程里常见的理论要点，也提供了从音频预处理、特征提取到解码识别的实操脚本。

## 1. 语音对话系统的基本组成和工作原理

一个完整的语音对话系统通常分为 5 层：

1. **前端采集**：麦克风采样，把空气中的压力波变成数字音频。
2. **音频预处理**：降噪、去静音、重采样、归一化。
3. **自动语音识别（ASR）**：把语音声学特征映射成文字。
4. **自然语言理解/对话管理**：理解意图，决定回复策略。
5. **语音合成（TTS）**：把文本回复重新合成为语音。

本实验聚焦第 2 到第 3 层，也就是离线语音识别核心链路。

## 2. 语音识别的基本原理

语音识别的基本任务是求解：

`W* = argmax P(W|X) = argmax P(X|W) P(W)`

其中：

- `X` 是输入的声学特征序列。
- `W` 是输出的词或字序列。
- `P(X|W)` 由**声学模型**提供。
- `P(W)` 由**语言模型**提供。

经典系统采用 “特征提取 + 声学模型 + 解码搜索” 三段式。现代深度学习系统会让声学模型更强，甚至把其中几段合并成端到端模型，但核心目标仍然是找到最可能的文本序列。

## 3. 音频预处理

本仓库的 `scripts/preprocess_audio.py` 做了这几步：

1. 读入 WAV 文件，自动转成单声道。
2. 去直流分量。
3. 按帧能量裁掉首尾静音。
4. 重采样到 16 kHz。
5. 做 80 Hz 到 7.6 kHz 的带通滤波。
6. 做预加重（pre-emphasis）。
7. 做峰值归一化。

这一步的作用是减少无信息成分，提高后续特征的稳定性。

## 4. 语音参数和特征提取

语音不能直接拿原始波形逐点做识别，所以通常会提取短时特征。本实验提取了：

- **帧能量**：刻画音量变化。
- **过零率（ZCR）**：辅助区分清辅音、浊音、静音。
- **Filter Bank**：更贴近人耳频带划分。
- **MFCC**：传统 ASR 中最常用的倒谱特征。
- **Delta / Delta-Delta**：描述动态变化。

输出目录会保存：

- `mfcc.npy`
- `delta.npy`
- `delta2.npy`
- `fbank.npy`
- `frame_energy.npy`
- `feature_summary.json`

## 5. 特征分类

“特征分类” 可以理解成：基于提取出来的特征去区分不同帧、音素或类别。教学里常见两条路线：

1. **浅层分类**：GMM、SVM、KNN，用 MFCC 等特征做分类。
2. **深度分类**：DNN、CNN、RNN、Transformer，直接从特征序列学习映射。

本实验没有单独训练一个分类器，而是把 MFCC 等特征直接送给现成的深度声学模型做识别。与此同时，`feature_summary.json` 里给出了 `voiced_frame_ratio` 等统计量，方便你把“有声/无声/静音帧”作为入门级特征分类观察点。

## 6. 声学模型

声学模型负责估计 `P(X|W)` 或与之等价的状态后验概率。发展路径大致是：

- GMM-HMM
- DNN-HMM
- TDNN / CNN / LSTM
- CTC / RNN-T / Attention / Transducer / Whisper 类端到端模型

本实验采用 **Vosk** 的离线中文模型，它底层延续了 Kaldi 体系，适合在树莓派这种 CPU 设备上做本地识别。

## 7. 语音解码

解码器的职责是把声学模型分数、词典约束和语言模型分数组合起来，在巨大的候选空间里找最优路径。常见实现是 Beam Search / WFST Search。

在这条实验链路中：

- `scripts/run_vosk_asr.py` 是解码入口；
- Vosk/Kaldi 内部负责帧级打分与搜索；
- 识别结果保存在 `asr_result.json`。

## 8. 语言模型和搜索算法

语言模型用于约束句子是否合法、常不常见。例如：

- “树莓派 五” 比 “树莓 排五” 更合理；
- “语音识别 实验” 比随机字串更合理。

常见语言模型包括：

- N-gram
- RNN LM
- Transformer LM

搜索算法通常使用：

- Viterbi
- Beam Search
- WFST

本实验里的 Vosk 模型默认自带语言模型与搜索图。你也可以给 `scripts/run_vosk_asr.py` 传 `--grammar-file`，用一个 JSON 短语表做受限解码，观察搜索空间缩小后的效果。

## 9. 深度学习在语音识别中的应用

深度学习主要改变了三个地方：

1. **更强的声学建模能力**：TDNN、LSTM、Conformer、Whisper。
2. **更少的人工特征依赖**：从 “MFCC + GMM-HMM” 走向 “Log-Mel + 深度网络”，甚至直接端到端。
3. **更强的上下文建模**：语言模型和跨帧依赖可以学得更深。

在资源受限设备上，常见工程折中是：

- 小模型离线本地跑；
- 大模型在服务器侧跑；
- 或者边缘端先做唤醒词和前端预处理，再把长语音发到云端。

树莓派 5 更适合小型离线模型、关键词识别或短句转写实验。

## 10. 实践：搭建一个简单的语音识别系统

### 10.1 仓库结构

```text
resp_lanu/
├── README.md
├── requirements.txt
├── resp_lanu/
│   ├── audio.py
│   ├── asr.py
│   └── features.py
├── scripts/
│   ├── setup_pi.sh
│   ├── record_audio.sh
│   ├── preprocess_audio.py
│   ├── extract_features.py
│   ├── run_vosk_asr.py
│   └── run_pipeline.sh
└── sample_audio/
```

### 10.2 在本机通过 SSH 操作树莓派 5

如果 SSH 别名已经配置成 `pi5`，可以直接执行：

```bash
rsync -av --delete \
  --exclude .venv \
  --exclude artifacts \
  --exclude models \
  ./ pi5:~/resp_lanu/
ssh pi5 'cd ~/resp_lanu && bash scripts/setup_pi.sh'
ssh pi5 'cd ~/resp_lanu && bash scripts/run_pipeline.sh'
```

如果想演示受限语法搜索，可以把第 4 个参数指向 JSON 短语表：

```bash
ssh pi5 'cd ~/resp_lanu && bash scripts/run_pipeline.sh sample_audio/demo_cn.wav demo_cn_grammar "" sample_audio/demo_cn_grammar.json'
```

如果想对领域词做后处理纠正，可以再传第 5 个参数，指向短语提示文件：

```bash
ssh pi5 'cd ~/resp_lanu && bash scripts/run_pipeline.sh sample_audio/demo_cn.wav demo_cn_hints "" sample_audio/demo_cn_grammar.json sample_audio/demo_cn_phrase_hints.json'
```

### 10.3 如果树莓派接了麦克风

先录音：

```bash
ssh pi5 'cd ~/resp_lanu && bash scripts/record_audio.sh sample_audio/live_record.wav 5'
ssh pi5 'cd ~/resp_lanu && bash scripts/run_pipeline.sh sample_audio/live_record.wav live_record'
```

### 10.4 当前实验流程

1. 准备一个 WAV 输入。
2. 做预处理，统一成 16 kHz 单声道 PCM。
3. 提取 MFCC / Delta / Filter Bank。
4. 载入 Vosk 中文模型。
5. 解码得到文本。
6. 在 `artifacts/<run_tag>/` 保存完整实验结果。

### 10.5 短语提示后处理

当小模型把领域词识别成近音字，比如把“树莓派五”识别成“数 没 派 五”时，可以给 `scripts/run_vosk_asr.py` 传 `--phrase-hints-file`，或给 `scripts/run_pipeline.sh` 传第 5 个参数，让它在解码后做一层轻量纠正。

短语提示文件格式支持：

- 字符串列表：只做“把空格分开的词重新并回目标短语”。
- 对象列表：`{"phrase": "树莓派五", "aliases": ["数 没 派 五"]}`，既能合并词，也能把常见误识别别名纠正回标准写法。

仓库示例见 `sample_audio/demo_cn_phrase_hints.json`。

### 10.6 结果判读

- 看 `preprocess_summary.json`：确认采样率、裁剪时长、归一化结果。
- 看 `features/feature_summary.json`：确认 MFCC 维度、能量和过零率。
- 看 `asr_result.json`：确认 `raw_transcript`、后处理后的 `transcript`、`corrections` 和词级时间戳。

## 11. 为什么这套方案适合树莓派 5

- 完全离线，不依赖云接口。
- 依赖轻，CPU 就能跑。
- 保留了经典 ASR 链路的教学可解释性。
- 能从 “音频预处理 -> 特征 -> 声学模型 -> 解码” 一路观察下来。

## 12. 下一步可扩展的实验

1. 接 USB 麦克风，改成实时流式识别。
2. 对比中文小模型和英文小模型的延迟、精度、内存占用。
3. 增加语法约束，观察受限解码带来的提升。
4. 把 Vosk 替换成 Whisper.cpp，对比深度端到端方案。
5. 加入唤醒词前端，做简易语音助手。
