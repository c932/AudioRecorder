#!/bin/sh
# 容器入口：
# 1. 首次启动把镜像内置的默认词库/题库播种进挂载的数据卷（不覆盖已有文件）
# 2. 用 edge-tts 生成 CosyVoice 参考音频，注册为预置说话人（不再每次请求上传）
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

# ---- 用 edge-tts 生成 CosyVoice 参考音频（多个说话人） ----
VOICES_DIR="/app/src/data/cosyvoice_voices"
mkdir -p "$VOICES_DIR"

generate_voice() {
  # $1=spk_id  $2=edge-tts voice  $3=reference text
  spk_id="$1"
  edge_voice="$2"
  ref_text="$3"
  out_wav="$VOICES_DIR/${spk_id}.wav"

  if [ -f "$out_wav" ] && head -c 4 "$out_wav" | grep -q RIFF; then
    echo "[entrypoint] 参考音频已存在: $spk_id"
    return 0
  fi

  echo "[entrypoint] 生成参考音频: $spk_id ($edge_voice)..."
  TMP_MP3=$(mktemp --suffix=.mp3)
  python3 -c "
import asyncio, edge_tts
async def gen():
    c = edge_tts.Communicate('$ref_text', '$edge_voice')
    await c.save('$TMP_MP3')
asyncio.run(gen())
" 2>/dev/null && \
  ffmpeg -y -i "$TMP_MP3" -ar 16000 -ac 1 -sample_fmt s16 "$out_wav" 2>/dev/null && \
  rm -f "$TMP_MP3" && \
  echo "[entrypoint] 参考音频已生成: $spk_id" || \
  echo "[entrypoint] ⚠️ 生成失败: $spk_id"
}

# 英文参考音频
generate_voice "en_female" "en-US-AriaNeural" \
  "Hello, this is a reference voice for text to speech synthesis. The weather is beautiful today."
generate_voice "en_male" "en-US-GuyNeural" \
  "Hello, this is a reference voice for text to speech synthesis. The weather is beautiful today."

# 中文参考音频
generate_voice "zh_female" "zh-CN-XiaoxiaoNeural" \
  "你好，这是一段用于语音合成的参考音频。今天天气真好。"
generate_voice "zh_male" "zh-CN-YunxiNeural" \
  "你好，这是一段用于语音合成的参考音频。今天天气真好。"

# ---- 向 CosyVoice 注册说话人（用 Python + requests，容器无 curl） ----
COSYVOICE_URL="${COSYVOICE_URL:-http://host.docker.internal:50000}"

echo "[entrypoint] 等待 CosyVoice 服务就绪并注册说话人..."
python3 -c "
import time, sys, requests
url = '$COSYVOICE_URL'
voices_dir = '$VOICES_DIR'

# 等待 CosyVoice 就绪
for i in range(1, 31):
    try:
        r = requests.get(f'{url}/list_speakers', timeout=5)
        if r.ok:
            print(f'[entrypoint] CosyVoice 已就绪（第 {i} 次尝试）')
            break
    except Exception:
        pass
    if i % 5 == 0:
        print(f'[entrypoint] CosyVoice 未就绪，已等待 {i * 5}秒...')
    time.sleep(5)
else:
    print('[entrypoint] ⚠️ CosyVoice 等待超时，跳过注册')
    sys.exit(0)

# 注册说话人
for spk in ['en_female', 'en_male', 'zh_female', 'zh_male']:
    wav_path = f'{voices_dir}/{spk}.wav'
    try:
        with open(wav_path, 'rb') as f:
            r = requests.post(f'{url}/register_speaker',
                data={'spk_id': spk},
                files={'prompt_wav': (f'{spk}.wav', f, 'audio/wav')},
                timeout=60)
        if r.ok:
            print(f'[entrypoint] 注册成功: {spk} → {r.json()}')
        else:
            print(f'[entrypoint] ⚠️ 注册失败: {spk} → {r.status_code} {r.text[:100]}')
    except FileNotFoundError:
        print(f'[entrypoint] ⚠️ 参考音频不存在: {wav_path}')
    except Exception as e:
        print(f'[entrypoint] ⚠️ 注册失败: {spk} → {e}')

print('[entrypoint] 说话人注册完成')
" || echo "[entrypoint] ⚠️ 注册脚本执行出错"

# ---- HTTPS 证书检测 ----
if [ -f /certs/cert.pem ] && [ -f /certs/key.pem ]; then
  export ENGLISH_COACH_SSL_CERT=/certs/cert.pem
  export ENGLISH_COACH_SSL_KEY=/certs/key.pem
  echo "[entrypoint] 检测到 /certs 证书，以 HTTPS 启动"
else
  echo "[entrypoint] 未检测到 /certs 证书，以 HTTP 启动（手机/iPad 录音需 HTTPS，见 deploy/README.md）"
fi

exec "$@"
