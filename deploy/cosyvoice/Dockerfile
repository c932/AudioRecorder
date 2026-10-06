# CosyVoice2 TTS 服务 — 中英混合 GPU 加速
# 基于官方 Dockerfile 修复版（解决 setuptools/pkg_resources 兼容问题，
# 去掉 tensorrt/gradio/deepspeed 等不需要的依赖）
# 构建上下文为 NUC 上的 ~/CosyVoice（docker-compose.yml 里 context: /home/manfred/CosyVoice）
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /opt/CosyVoice

RUN sed -i 's@/archive.ubuntu.com/@/mirrors.aliyun.com/@g' /etc/apt/sources.list \
    && apt-get update -y \
    && apt-get -y install --no-install-recommends git unzip git-lfs g++ \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install

# 约束文件：防止后续 pip 安装升级 torch/torchaudio/setuptools（ABI 兼容性）
RUN printf 'setuptools<70\ntorch==2.0.1\ntorchaudio==2.0.1\n' > /opt/pip-constraints.txt

# 修复：旧版 pip + 新版 setuptools 不含 pkg_resources
RUN pip3 install --no-cache-dir "setuptools<70" wheel

# 从构建上下文复制 CosyVoice 仓库（避免每次 git clone 网络不稳定）
# docker-compose.yml 里 context: /home/manfred/CosyVoice
COPY . CosyVoice/

# 精简依赖：分批安装，避免单次大包超时导致整层重做
# 每批都带 --constraint 防止 torch/torchaudio/setuptools 被升级
# 批次1：核心小包（快速安装，建立缓存层）
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 120 --retries 5 \
    --constraint /opt/pip-constraints.txt \
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
    --constraint /opt/pip-constraints.txt \
    numpy==1.26.4 \
    librosa==0.10.2 \
    soundfile==0.12.1 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次3：ML 大包（transformers/lightning/modelscope — 体积大，易超时）
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 180 --retries 5 \
    --constraint /opt/pip-constraints.txt \
    transformers==4.51.3 \
    lightning==2.2.4 \
    modelscope==1.20.0 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次3b：openai-whisper 依赖（tiktoken — 不含 torch）
RUN pip3 install --no-cache-dir --timeout 120 --retries 5 \
    --constraint /opt/pip-constraints.txt \
    tiktoken==0.7.0 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次3c：openai-whisper 本体（--no-deps 防止升级 torch，
#   --no-build-isolation 用系统 setuptools<70 编译）
RUN pip3 install --no-cache-dir --no-deps --no-build-isolation --timeout 180 --retries 5 \
    openai-whisper==20231117 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次4：GPU 推理（onnxruntime-gpu ~200MB，单独一层便于重试）
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 180 --retries 5 \
    --constraint /opt/pip-constraints.txt \
    onnxruntime-gpu==1.18.0 \
    x-transformers==2.11.24 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 编译 gRPC proto（client 不用，但服务端 import 需要）
RUN cd CosyVoice/runtime/python/grpc \
    && pip3 install --no-cache-dir --timeout 120 --retries 5 \
        --constraint /opt/pip-constraints.txt \
        grpcio==1.57.0 grpcio-tools==1.57.0 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn \
    && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. cosyvoice.proto

ENV MODELSCOPE_CACHE=/opt/CosyVoice/models

EXPOSE 50000

CMD ["bash", "-c", "cd /opt/CosyVoice/CosyVoice/runtime/python/fastapi && python3 server.py --port 50000 --model_dir iic/CosyVoice2-0.5B"]
