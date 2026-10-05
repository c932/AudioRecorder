# Web 版部署（Ubuntu NUC · Docker · 局域网）

把「少儿英语发音教练」部署为局域网 Web 服务：单容器跑 FastAPI 后端 +
React 前端，GPU 加速 wav2vec2（发音评分）与 Whisper（语音识别），
局域网内 iPad / 手机 / 电脑浏览器直接使用。MiniCPM-o 与 LLM 服务跑在
宿主机或局域网其他机器上（容器外）。

## 1. 前置条件（NUC 上一次性安装）

- NVIDIA 驱动正常（`nvidia-smi` 有输出）
- Docker Engine ≥ 24 + Compose v2（`docker compose version`）
- nvidia-container-toolkit（容器内使用 GPU）：

```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

## 2. 首次部署

```bash
git clone <本仓库> && cd AudioRecorder/deploy
docker compose up -d --build
```

- 首次构建需下载 PyTorch CUDA 轮子等（约 5GB），视网速 10–30 分钟
- 首次启动自动把内置词库/题库播种到 `deploy/data/`（不覆盖已有文件）
- 镜像约 8GB；用户数据与模型缓存都在挂载卷里，重建镜像不丢失

## 3. 放入 config.json（必需）

`config.json`（LLM / MiniCPM-o / 密钥配置）不进 git 也不进镜像。
从桌面版机器把它拷贝到 `deploy/data/config.json`：

- 指向局域网 IP 的服务（如 LLM `192.168.50.200:9090`）原样可用
- 指向 `127.0.0.1` / `localhost` 的服务（如宿主机上的 MiniCPM-o），
  容器启动时会自动改写为 `host.docker.internal`（compose 已配 host-gateway），
  无需手动修改

## 4. HTTPS 与手机 / iPad 录音（重要）

浏览器只在**安全上下文**（https 或 localhost）开放麦克风。
`http://<局域网IP>:8000` 在 iPad / 手机上**无法录音**（页面能浏览、能打字，
但麦克风被浏览器禁用）。

### 方案 A（推荐）：mkcert 局域网证书

```bash
sudo apt install -y mkcert
mkcert -install
mkcert 192.168.50.10        # ← 换成 NUC 的局域网 IP
# 生成两个文件，例如 192.168.50.10+1.pem（证书）与 192.168.50.10+1-key.pem（私钥）
mkdir -p certs
cp "192.168.50.10+1.pem" certs/cert.pem
cp "192.168.50.10+1-key.pem" certs/key.pem
docker compose restart      # 之后访问 https://192.168.50.10:8000
```

（文件名里的序号以实际输出为准。）

各设备安装 mkcert 根证书后才能信任该 HTTPS 站点
（`mkcert -CAROOT` 可查看 rootCA.pem 的路径）：

| 设备 | 步骤 |
|---|---|
| iPad / iPhone | AirDrop 或发送 rootCA.pem → 点击安装描述文件 → 设置 → 通用 → 关于本机 → 证书信任设置 → 勾选 mkcert |
| Android | 设置 → 安全 → 更多安全设置 → 加密与凭据 → 安装证书 → CA 证书 |
| Windows | 双击 rootCA.pem → 安装到「受信任的根证书颁发机构」 |

### 方案 B：纯 HTTP（仅桌面 Chrome 可录音）

桌面 Chrome 打开 `chrome://flags/#unsafely-treat-insecure-origin-as-secure`，
填入 `http://<NUC-IP>:8000` 并重启浏览器。iPad / 手机在此方案下不能录音评分。

## 5. 预热模型（可选，推荐）

```bash
docker compose run --rm backend python deploy/prewarm_models.py
```

把 wav2vec2 + Whisper 下载进 `hf-cache` 卷（约 3GB，一次性）。此后容器重启
不再联网下载。国内网络慢可在 compose 的 environment 加
`HF_ENDPOINT=https://hf-mirror.com`。

## 6. 验证

```bash
curl http://127.0.0.1:8000/api/health     # {"status":"ok"}
docker compose exec backend nvidia-smi    # 容器内能看到 GPU
sudo ufw allow 8000/tcp                   # 防火墙放行（按需）
```

浏览器（与 NUC 同一 WiFi）访问 `https://<NUC-IP>:8000`，
首页 → 跟读练习 → 听标准音 → 录音 → 出分数。

## 7. 日常运维

```bash
docker compose logs -f                     # 看日志
docker compose restart                     # 重启
git pull && docker compose up -d --build   # 更新版本
docker compose down                        # 停止（数据保留在 deploy/data 与 hf-cache 卷）
```

数据备份：拷贝 `deploy/data/` 即可（词库、进度、配置）；模型缓存卷可随时重建。

## 常见问题

| 症状 | 处理 |
|---|---|
| 容器内 `nvidia-smi` 失败 | nvidia-container-toolkit 未安装，或装完没重启 docker |
| omni / LLM 请求失败 | 看日志确认 config.json 地址已就位；宿主机服务需监听 0.0.0.0（不能只听 127.0.0.1） |
| 手机点录音提示「需要安全连接」 | 按第 4 节配 HTTPS 证书 |
| TTS 无声音 | edge-tts 走微软在线服务，NUC 需能访问外网 |
| 首次评分很慢 | 正在下载模型；先跑第 5 节预热 |
