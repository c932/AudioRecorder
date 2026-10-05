#!/bin/sh
# 容器入口：
# 1. 首次启动把镜像内置的默认词库/题库播种进挂载的数据卷（不覆盖已有文件）
# 2. 检测到 /certs 下有证书时自动启用 HTTPS（浏览器麦克风权限需要安全上下文）
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

if [ -f /certs/cert.pem ] && [ -f /certs/key.pem ]; then
  export ENGLISH_COACH_SSL_CERT=/certs/cert.pem
  export ENGLISH_COACH_SSL_KEY=/certs/key.pem
  echo "[entrypoint] 检测到 /certs 证书，以 HTTPS 启动"
else
  echo "[entrypoint] 未检测到 /certs 证书，以 HTTP 启动（手机/iPad 录音需 HTTPS，见 deploy/README.md）"
fi

exec "$@"
