// 语音播放 — 后端 TTS（edge-tts → MP3）+ 会话内缓存/预取 + 本地鼓励音效。
let audioEl: HTMLAudioElement | null = null;
let speakToken = 0;

// text → objectURL 缓存（同一文本只合成一次，重放零等待）
const urlCache = new Map<string, string>();
// text → 进行中的请求（并发去重）
const pending = new Map<string, Promise<string>>();

async function fetchTts(text: string): Promise<string> {
  const hit = urlCache.get(text);
  if (hit) return hit;
  const inflight = pending.get(text);
  if (inflight) return inflight;
  const p = (async () => {
    const res = await fetch("/api/practice/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error("语音合成失败");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    urlCache.set(text, url);
    return url;
  })();
  pending.set(text, p);
  try {
    return await p;
  } finally {
    pending.delete(text);
  }
}

/** 后台预取一批文本的发音（当前词在前，3 路并发）。 */
export function prefetchTts(texts: string[]) {
  const queue = texts.filter((t) => t.trim() && !urlCache.has(t) && !pending.has(t));
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
