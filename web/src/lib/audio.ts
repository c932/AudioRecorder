// 语音播放 — 后端 TTS（edge-tts → MP3）+ 本地鼓励音效。
let audioEl: HTMLAudioElement | null = null;

export function stopAudio() {
  if (audioEl) {
    audioEl.pause();
    audioEl = null;
  }
}

export async function speak(text: string): Promise<void> {
  stopAudio();
  if (!text.trim()) return;
  const res = await fetch("/api/practice/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error("语音合成失败");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const el = new Audio(url);
  audioEl = el;
  return new Promise((resolve) => {
    el.onended = () => {
      URL.revokeObjectURL(url);
      if (audioEl === el) audioEl = null;
      resolve();
    };
    el.onerror = () => {
      URL.revokeObjectURL(url);
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
