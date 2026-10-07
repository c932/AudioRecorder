// 语音播放 — 后端 TTS（CosyVoice GPU / edge-tts 回退）+ 会话内缓存/预取 + 本地鼓励音效。
let audioEl: HTMLAudioElement | null = null;
let speakToken = 0;

// 当前 TTS 音色（从设置页同步，默认英文女声）
let currentVoice: string = "";

/** 设置全局 TTS 音色（由 SettingsPage 调用）。 */
export function setTtsVoice(voice: string) {
  currentVoice = voice;
  // 音色变更后清空缓存，避免旧音色的音频残留
  for (const url of urlCache.values()) URL.revokeObjectURL(url);
  urlCache.clear();
  pending.clear();
}

/** 获取当前 TTS 音色。 */
export function getTtsVoice(): string {
  return currentVoice;
}

/** 从后端配置加载 TTS 音色（应用启动时调用一次）。 */
let voiceInited = false;
export async function initTtsVoiceFromConfig() {
  if (voiceInited) return;
  voiceInited = true;
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      const cfg = await res.json();
      const spk = String(cfg.cosyvoice_spk ?? "英文女");
      currentVoice = spk;
    }
  } catch {
    // 加载失败用默认值（空串，后端会自动选英文女）
  }
}

// (text, voice) → objectURL 缓存（同文本同音色只合成一次，重放零等待）
const urlCache = new Map<string, string>();
// (text, voice) → 进行中的请求（并发去重）
const pending = new Map<string, Promise<string>>();

function cacheKey(text: string): string {
  return `${text}\0${currentVoice}`;
}

async function fetchTts(text: string): Promise<string> {
  const key = cacheKey(text);
  const hit = urlCache.get(key);
  if (hit) return hit;
  const inflight = pending.get(key);
  if (inflight) return inflight;
  const p = (async () => {
    const body: Record<string, string> = { text };
    if (currentVoice) body.voice = currentVoice;
    const res = await fetch("/api/practice/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("语音合成失败");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    urlCache.set(key, url);
    return url;
  })();
  pending.set(key, p);
  try {
    return await p;
  } finally {
    pending.delete(key);
  }
}

/** 后台预取一批文本的发音（当前词在前，3 路并发）。 */
export function prefetchTts(texts: string[]) {
  const queue = texts.filter((t) => t.trim() && !urlCache.has(cacheKey(t)) && !pending.has(cacheKey(t)));
  let i = 0;
  const worker = async () => {
    while (i < queue.length) {
      const t = queue[i++];
      try {
        await fetchTts(t);
      } catch {
        /* 预取失败不打扰，真正播放时再报错 */
      }
    }
  };
  void worker();
  void worker();
  void worker();
}

export function stopAudio() {
  speakToken++; // 让进行中的 speak 在拿到音频后不再播放
  if (audioEl) {
    audioEl.pause();
    audioEl = null;
  }
}

export async function speak(text: string): Promise<void> {
  stopAudio();
  const token = speakToken; // 本次播放的令牌（stopAudio 已递增）
  if (!text.trim()) return;
  const url = await fetchTts(text);
  if (token !== speakToken) return; // 期间已切到别的播放/页面
  const el = new Audio(url);
  audioEl = el;
  return new Promise((resolve) => {
    el.onended = () => {
      if (audioEl === el) audioEl = null;
      resolve();
    };
    el.onerror = () => {
      if (audioEl === el) audioEl = null;
      resolve();
    };
    el.play().catch(() => resolve());
  });
}

export function playSoundForScore(score: number) {
  const name =
    score >= 90 ? "perfect" : score >= 75 ? "excellent" : score >= 60 ? "good" : "encourage";
  const el = new Audio(`/sounds/${name}.wav`);
  el.play().catch(() => {});
}
