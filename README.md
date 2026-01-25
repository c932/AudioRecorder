# 🦜 少儿英语发音教练 (English Pronunciation Coach)

这就一款专为儿童设计的智能化、本地化英语口语训练工具。它利用 **OpenAI Whisper** 和 **Ollama** 等前沿 AI 技术，提供高精度的语音识别和自然、亲切的双语反馈，且核心功能完全无需依赖云端 API，保护隐私并支持离线运行。

![Mascot](src/resources/images/mascot.png)

## ✨ 核心功能 (Key Features)

- **🔒完全本地化 AI (Fully Local AI)**:
  - **听 (Ears)**: 使用 `openai-whisper` (Small/Medium 模型) 进行 GPU 加速识别，识别准确率远超传统离线引擎。
  - **想 (Brain)**: 集成当本地 LLM (如 Ollama/Qwen)，能像真人老师一样提供具体的中文纠音建议 (例如：“元音发音要饱满一点”、“注意连读”)。
- **⚡ 零延迟体验 (Zero Latency)**:
  - **智能预加载**: 启动时自动预热模型，消除首词识别卡顿。
  - **优化 VAD**: 搭载高灵敏度语音活动检测，支持“自动化连续练习”模式，无需手动点击。
- **🎮 游戏化体验 (Gamified)**:
  - **双语反馈**: 提供 Google TTS (英语) 和 Microsoft Edge Neural TTS (中文 - 晓晓) 的生动语音反馈。
  - **视觉激励**: 1-3 星评分系统，高分将获得金色奖杯 🏆，低分也有吉祥物暖心鼓励。
  - **吉祥物伴学**: 可爱的 AI 机器人全程陪伴学习。
- **📚 智能练习 (Smart Practice)**:
  - **PDF 导入**: 支持直接从课本或练习册的 PDF 中导入词汇表。
  - **错题本 (Mistake Review)**: 自动记录低分单词，提供“听标准音”功能进行针对性复习。
  - **复习策略**: 支持随机乱序、智能复习 (优先低分) 和 不重复模式。

## 🛠️ 安装指南 (Installation)

### 环境要求
1.  **Python 3.10+**
2.  **FFmpeg**: 音频处理必须组件。[下载 FFmpeg](https://ffmpeg.org/download.html) 并将其 `bin` 目录添加到系统环境变量 PATH 中。
3.  **NVIDIA 显卡**: 推荐使用 RTX 3060 或以上显卡以获得最佳 Whisper 加速体验。

### 第一步：安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 第二步：安装 PyTorch (CUDA 版)
为了启用 GPU 加速 (Whisper 运行的关键)，请运行以下命令：
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### 第三步：配置 Ollama (可选，推荐)
如需启用“AI 纠音建议”功能：
1.  下载并安装 [Ollama](https://ollama.com/)。
2.  拉取一个中文能力较强的模型 (例如 Qwen2.5 或 Qwen3)：
    ```bash
    ollama run qwen3:4b
    ```

## 🚀 使用说明 (Usage)

启动主程序：
```bash
python main.py
```

### 快捷启动 (Quick Start)
为方便使用，项目提供了快捷启动脚本：
- **`run.bat`**: 自动激活环境并启动程序 (有控制台窗口)。
- **`start_silent.vbs`**: **[推荐]** 静默启动，不显示黑色控制台窗口，适合日常使用。


### 设置建议 (Settings)
点击主页右上角的 **Settings** 按钮进行配置：
- **Audio Device**: 选择正确的麦克风设备。
- **STT Engine**: 强烈建议选择 `Local Whisper (GPU)` 以获得最佳识别效果。
- **Practice Count**: 设置每组练习的单词数量 (默认: 20)。
- **Feedback Language**: 建议选择 `Chinese (中文)`，反馈更加亲切有趣。
- **Advanced (高级设置)**: 可调节 **Scoring Sensitivity** (评分灵敏度)，包括自信度门槛 (Threshold) 和严选模式 (90+ Lock)，满足不同水平的学习需求。

## 📂 项目结构

```
AudioRecorder/
├── src/
│   ├── core/              # 核心逻辑 (录音机, AI 评估器, 练习管理器)
│   ├── ui/                # 用户界面 (PyQt6)
│   ├── resources/         # 资源文件 (图片, 音效)
│   ├── tools/             # 工具脚本 (声音生成器)
│   └── data/              # 用户数据 (words.json, 统计信息)
├── requirements.txt
├── main.py                # 程序入口
└── README.md
```

## 🤝 致谢
- **OpenAI Whisper**: 提供了强大的语音识别能力。
- **Microsoft Edge TTS**: 提供了自然逼真的中文语音合成。
- **PyQt6**: 构建了流畅的桌面客户端界面。
