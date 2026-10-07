# Qwen3-TTS 服务 — 中英文 TTS，内置 9 种音色，无需参考音频
# 模型从 ModelScope 下载，PyTorch + CUDA
FROM pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /opt/qwen-tts

# 安装 qwen-tts + FastAPI + modelscope（国内镜像）
# qwen-tts 不需要 git-lfs，模型通过 Python 下载
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn \
    qwen-tts \
    fastapi==0.115.6 \
    uvicorn==0.30.0 \
    python-multipart==0.0.9 \
    soundfile==0.12.1 \
    modelscope

# flash-attn（可选，显著加速推理；编译需约 5 分钟）
RUN pip install --no-cache-dir --no-build-isolation \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn \
    flash-attn || echo "flash-attn install failed, will use sdpa fallback"

# 模型缓存目录
ENV MODELSCOPE_CACHE=/opt/qwen-tts/models

COPY server.py .

EXPOSE 50000

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=120s \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 50000), timeout=5).close()"

CMD ["python3", "server.py", "--port", "50000", "--model_dir", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"]
