# CosyVoice2 TTS 服务 — 中英混合 GPU 加速
# 基于官方 Dockerfile 修复版（解决 setuptools/pkg_resources 兼容问题，
# 去掉 tensorrt/gradio/deepspeed 等不需要的依赖）
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

# 精简依赖：分批安装，避免单次大包超时导致整层重做
# 批次1：核心小包（快速安装，建立缓存层）
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 120 --retries 5 \
    conformer==0.3.2 \
    diffusers==0.29.0 \
    fastapi==0.115.6 \
    Hydra-core==1.3.2 \
    HyperPyYAML==1.2.3 \
    inflect==7.3.1 \
    pydantic==2.7.0 \
    rich==13.7.1 \
    omegaconf==2.3.0 \
    uvicorn==0.30.0 \
    wetext==0.0.4 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次2：科学计算大包（numpy/librosa/soundfile）
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 120 --retries 5 \
    numpy==1.26.4 \
    librosa==0.10.2 \
    soundfile==0.12.1 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次3：ML 大包（transformers/lightning/modelscope/whisper — 体积大，易超时）
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 180 --retries 5 \
    transformers==4.51.3 \
    lightning==2.2.4 \
    modelscope==1.20.0 \
    openai-whisper==20231117 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次4：GPU 推理（onnxruntime-gpu ~200MB，单独一层便于重试）
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 180 --retries 5 \
    onnxruntime-gpu==1.18.0 \
    x-transformers==2.11.24 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 编译 gRPC proto（client 不用，但服务端 import 需要）
# 先修复 setuptools：前面批次可能把 setuptools 升级到 70+，导致 pkg_resources 丢失
RUN cd CosyVoice/runtime/python/grpc \
    && pip3 install --no-cache-dir "setuptools<70" \
        -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn \
    && pip3 install --no-cache-dir --timeout 120 --retries 5 \
        grpcio==1.57.0 grpcio-tools==1.57.0 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn \
    && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. cosyvoice.proto

ENV MODELSCOPE_CACHE=/opt/CosyVoice/models

EXPOSE 50000

CMD ["bash", "-c", "cd /opt/CosyVoice/CosyVoice/runtime/python/fastapi && python3 server.py --port 50000 --model_dir iic/CosyVoice2-0.5B"]
