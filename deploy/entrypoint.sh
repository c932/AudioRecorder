#!/bin/sh
# 容器入口：
# 1. 首次启动把镜像内置的默认词库/题库播种进挂载的数据卷（不覆盖已有文件）
# 2. 等待 Qwen3-TTS 服务就绪
# 3. 检测到 /certs 下有证书时自动启用 HTTPS（浏览器麦克风权限需要安全上下文）
# config.json（含密钥，不进 git/镜像）需手动放入 deploy/data/，见 README。
set -e

for f in /app/src/data-defaults/*.json; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  if [ ! -f "/app/src/data/$name" ]; then
    cp "$f" "/app/src/data/$name"
    echo "[entrypoint] 播种默认数据: $name"
  fi
done

# ---- 等待 Qwen3-TTS 服务就绪 ----
TTS_URL="${TTS_URL:-http://host.docker.internal:50000}"
echo "[entrypoint] 等待 Qwen3-TTS 服务就绪..."
python3 -c "
import time, requests
url = '$TTS_URL'
for i in range(1, 61):
    try:
        r = requests.get(f'{url}/speakers', timeout=5)
        if r.ok:
            data = r.json()
            print(f'[entrypoint] Qwen3-TTS 已就绪，音色: {list(data.get(\"speakers\", {}).keys())}')
            break
    except Exception:
        pass
    if i % 10 == 0:
        print(f'[entrypoint] Qwen3-TTS 未就绪，已等待 {i * 5}秒...')
    time.sleep(5)
else:
    print('[entrypoint] ⚠️ Qwen3-TTS 等待超时')
" || echo "[entrypoint] ⚠️ TTS 就绪检查出错"

# ---- HTTPS 证书检测 ----
if [ -f /certs/cert.pem ] && [ -f /certs/key.pem ]; then
  export ENGLISH_COACH_SSL_CERT=/certs/cert.pem
  export ENGLISH_COACH_SSL_KEY=/certs/key.pem
  echo "[entrypoint] 检测到 /certs 证书，以 HTTPS 启动"
else
  echo "[entrypoint] 未检测到 /certs 证书，以 HTTP 启动（手机/iPad 录音需 HTTPS，见 deploy/README.md）"
fi

exec "$@"
