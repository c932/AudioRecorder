# CosyVoice2 TTS 服务 — 中英混合 GPU 加速
# 精简自官方 requirements.txt：去掉 deepspeed/gradio/tensorrt（训练/演示用，推理不需要）
# 构建上下文为 NUC 上的 ~/CosyVoice（docker-compose.yml 里 context: /home/manfred/CosyVoice）
# 基础镜像 pytorch:2.0.1 已在 NUC 缓存；torch 2.3.1 通过 pip 升级（CosyVoice2 模型需要）
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /opt/CosyVoice

RUN sed -i 's@/archive.ubuntu.com/@/mirrors.aliyun.com/@g' /etc/apt/sources.list \
    && apt-get update -y \
    && apt-get -y install --no-install-recommends git unzip git-lfs g++ \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install

# 约束文件：防止 pip 意外升级 setuptools（pkg_resources 兼容）
RUN printf 'setuptools<70\n' > /opt/pip-constraints.txt

# 修复：旧版 pip + 新版 setuptools 不含 pkg_resources
RUN pip3 install --no-cache-dir "setuptools<70" wheel

# 升级 torch/torchaudio 到 2.3.1（CosyVoice2-0.5B 模型需要 2.3+ 的 parametrizations 格式）
# 用清华镜像 + 上交大 PyTorch 镜像
RUN pip3 install --no-cache-dir --timeout 300 --retries 5 \
    torch==2.3.1 torchaudio==2.3.1 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    --extra-index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cu121/ \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    --trusted-host mirror.sjtu.edu.cn

# 从构建上下文复制 CosyVoice 仓库
COPY . CosyVoice/

# 分批安装（从官方 requirements.txt 精简，去掉 deepspeed/gradio/tensorrt）
# 批次1：核心小包
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 120 --retries 5 \
    --constraint /opt/pip-constraints.txt \
    conformer==0.3.2 \
    diffusers==0.29.0 \
    fastapi==0.115.6 \
    fastapi-cli==0.0.4 \
    gdown==5.1.0 \
    hydra-core==1.3.2 \
    HyperPyYAML==1.2.3 \
    inflect==7.3.1 \
    omegaconf==2.3.0 \
    pydantic==2.7.0 \
    python-multipart==0.0.9 \
    rich==13.7.1 \
    uvicorn==0.30.0 \
    wetext==0.0.4 \
    wget==3.2 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次2：科学计算
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 120 --retries 5 \
    --constraint /opt/pip-constraints.txt \
    numpy==1.26.4 \
    librosa==0.10.2 \
    soundfile==0.12.1 \
    matplotlib==3.7.5 \
    pyworld==0.3.4 \
    pyarrow==18.1.0 \
    onnx==1.16.0 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次3：ML 大包（transformers 4.51.3 兼容 torch 2.3.1）
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 180 --retries 5 \
    --constraint /opt/pip-constraints.txt \
    transformers==4.51.3 \
    lightning==2.2.4 \
    modelscope==1.20.0 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次3b：tiktoken + protobuf（openai-whisper 依赖）
RUN pip3 install --no-cache-dir --timeout 120 --retries 5 \
    --constraint /opt/pip-constraints.txt \
    tiktoken==0.7.0 \
    protobuf==4.25 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次3c：openai-whisper（--no-deps + --no-build-isolation）
RUN pip3 install --no-cache-dir --no-deps --no-build-isolation --timeout 180 --retries 5 \
    openai-whisper==20231117 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 批次4：GPU 推理
RUN cd CosyVoice && pip3 install --no-cache-dir --timeout 180 --retries 5 \
    --constraint /opt/pip-constraints.txt \
    onnxruntime-gpu==1.18.0 \
    x-transformers==2.11.24 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn

# 编译 gRPC proto
RUN cd CosyVoice/runtime/python/grpc \
    && pip3 install --no-cache-dir --timeout 120 --retries 5 \
        --constraint /opt/pip-constraints.txt \
        grpcio==1.57.0 grpcio-tools==1.57.0 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host=pypi.tuna.tsinghua.edu.cn \
    && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. cosyvoice.proto

ENV MODELSCOPE_CACHE=/opt/CosyVoice/models

EXPOSE 50000

CMD ["bash", "-c", "cd /opt/CosyVoice/CosyVoice/runtime/python/fastapi && python3 server.py --port 50000 --model_dir iic/CosyVoice2-0.5B"]
