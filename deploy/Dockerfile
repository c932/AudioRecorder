# 少儿英语发音教练 Web 版镜像 — FastAPI + React 静态前端 + GPU (CUDA)
# 构建上下文为仓库根目录（docker-compose.yml 里 context: ..）
# 注意：不用 `# syntax=docker/dockerfile:1` 指令 — 它会从 Docker Hub 拉取
# 前端镜像，国内网络常 TLS 超时；Docker 29 内置 BuildKit 前端已支持
# COPY --chmod 等本文件用到的全部特性。

# ---------- 阶段 1：构建 React 前端（web/dist 不进 git，在镜像内构建） ----------
FROM node:20-alpine AS frontend
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---------- 阶段 2：后端运行时 ----------
FROM python:3.12-slim

# ffmpeg：浏览器 webm 录音转 WAV + Whisper 音频解码
# tzdata：速记复习按本地日期调度（TZ=Asia/Shanghai 需要它生效）
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖（版本与开发机 pip freeze 一致；torch 走 pytorch cu128 索引）
COPY deploy/requirements-web.txt /tmp/requirements-web.txt
RUN pip install --no-cache-dir -r /tmp/requirements-web.txt

# 后端代码 + 前端构建产物
COPY src/ ./src/
COPY run_web.py ./
COPY --from=frontend /build/dist ./web/dist

# 内置词库/题库移到种子目录；运行时 /app/src/data 是挂载卷（entrypoint 播种）。
# .dockerignore 已排除 src/data/config.json — 密钥不进镜像。
RUN mv src/data src/data-defaults && mkdir src/data

COPY deploy/prewarm_models.py ./deploy/prewarm_models.py
COPY --chmod=755 deploy/entrypoint.sh /entrypoint.sh

# g2p_en 依赖的 NLTK 资源（CMU 词典 + POS tagger）随仓库分发，烘焙进镜像
# （部署机可能连不上 raw.githubusercontent.com 的 NLTK 下载源，不联网下载）
COPY deploy/nltk_data /app/nltk_data
ENV NLTK_DATA=/app/nltk_data
RUN python -c "from src.core.gop.g2p import _ensure_nltk_resources; _ensure_nltk_resources()"

ENV ENGLISH_COACH_HEADLESS=1 \
    HF_HOME=/hf-cache \
    XDG_CACHE_HOME=/hf-cache \
    TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cuda_runtime/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.12/site-packages/nvidia/cufft/lib:/usr/local/lib/python3.12/site-packages/nvidia/curand/lib:/usr/local/lib/python3.12/site-packages/nvidia/cusolver/lib:/usr/local/lib/python3.12/site-packages/nvidia/cusparse/lib:/usr/local/lib/python3.12/site-packages/nvidia/cupti/lib:/usr/local/lib/python3.12/site-packages/nvidia/nvjitlink/lib:${LD_LIBRARY_PATH}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=5).close()"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "run_web.py"]
