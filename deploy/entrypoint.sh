#!/bin/sh
# 容器入口：
# 1. 首次启动把镜像内置的默认词库/题库播种进挂载的数据卷（不覆盖已有文件）
# 2. 确保 CosyVoice 英文参考音频存在（edge-tts 生成 + ffmpeg 转 WAV）
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

# 确保 CosyVoice 英文参考音频存在（16kHz mono WAV）
PROMPT_WAV="/app/src/data/cosyvoice_prompt.wav"
if [ ! -f "$PROMPT_WAV" ] || ! head -c 4 "$PROMPT_WAV" | grep -q RIFF; then
  echo "[entrypoint] 生成 CosyVoice 英文参考音频..."
  TMP_MP3=$(mktemp --suffix=.mp3)
  python3 -c "
import asyncio, edge_tts
async def gen():
    c = edge_tts.Communicate('Hello, this is a reference voice for text to speech synthesis.', 'en-US-AriaNeural')
    await c.save('$TMP_MP3')
asyncio.run(gen())
" 2>/dev/null && \
  ffmpeg -y -i "$TMP_MP3" -ar 16000 -ac 1 -sample_fmt s16 "$PROMPT_WAV" 2>/dev/null && \
  rm -f "$TMP_MP3" && \
  echo "[entrypoint] CosyVoice 英文参考音频已生成"
fi

if [ -f /certs/cert.pem ] && [ -f /certs/key.pem ]; then
  export ENGLISH_COACH_SSL_CERT=/certs/cert.pem
  export ENGLISH_COACH_SSL_KEY=/certs/key.pem
  echo "[entrypoint] 检测到 /certs 证书，以 HTTPS 启动"
else
  echo "[entrypoint] 未检测到 /certs 证书，以 HTTP 启动（手机/iPad 录音需 HTTPS，见 deploy/README.md）"
fi

exec "$@"
