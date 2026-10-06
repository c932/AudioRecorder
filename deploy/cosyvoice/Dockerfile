# CosyVoice2 TTS 服务 — 中英混合 GPU 加速
# 基于官方 Dockerfile 修复版（解决 setuptools/pkg_resources 兼容问题，
# 去掉 whisper/tensorrt/gradio 等不需要的依赖）
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /opt/CosyVoice

RUN sed -i 's@/archive.ubuntu.com/@/mirrors.aliyun.com/@g' /etc/apt/sources.list \
    && apt-get update -y \
    && apt-get -y install --no-install-recommends git unzip git-lfs g++ \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install

# 修复：旧版 pip + 新版 setuptools 不含 pkg_resources
RUN pip3 install --no-cache-dir "setuptools<70" wheel

# 克隆仓库（模型运行时从 ModelScope 下载，不烘焙进镜像）
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git

# 精简依赖：只装 TTS 推理需要的包，去掉 whisper/gradio/tensorrt/deepspeed 等
RUN cd CosyVoice && pip3 install --no-cache-dir \
    conformer==0.3.2 \
    diffusers==0.29.0 \
    fastapi==0.115.6 \
    Hydra-core==1.3.2 \
    HyperPyYAML==1.2.3 \
    inflect==7.3.1 \
    librosa==0.10.2 \
    lightning==2.2.4 \
    modelscope==1.20.0 \
    numpy==1.26.4 \
    omegaconf==2.3.0 \
    onnxruntime-gpu==1.18.0 \
    pydantic==2.7.0 \
    rich==13.7.1 \
    soundfile==0.12.1 \
    transformers==4.51.3 \
    x-transformers==2.11.24 \
    uvicorn==0.30.0 \
    wetext==0.0.4 \
    -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com

# 编译 gRPC proto（client 不用，但服务端 import 需要）
RUN cd CosyVoice/runtime/python/grpc \
    && pip3 install --no-cache-dir grpcio==1.57.0 grpcio-tools==1.57.0 \
        -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com \
    && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. cosyvoice.proto

ENV MODELSCOPE_CACHE=/opt/CosyVoice/models

EXPOSE 50000

CMD ["bash", "-c", "cd /opt/CosyVoice/CosyVoice/runtime/python/fastapi && python3 server.py --port 50000 --model_dir iic/CosyVoice2-0.5B"]
