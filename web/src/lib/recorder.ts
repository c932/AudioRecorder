// 浏览器录音 — MediaRecorder → base64（后端 ffmpeg 转 16kHz WAV 供 GOP/Whisper）。
import { useCallback, useRef, useState } from "react";

export interface Recording {
  b64: string;
  format: string;
}

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

function formatOf(mime: string): string {
  if (mime.includes("mp4")) return "mp4";
  if (mime.includes("ogg")) return "ogg";
  return "webm";
}

export function useRecorder() {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState("");
  const recRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const mimeRef = useRef("");
  const resolveRef = useRef<((r: Recording) => void) | null>(null);
  const stopSeqRef = useRef(0);

  const start = useCallback(async () => {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      const msg = "此浏览器不支持录音";
      setError(msg);
      throw new Error(msg);
    }
    if (!window.isSecureContext) {
      const msg = "录音需要安全连接（https 或 localhost），当前页面不满足";
      setError(msg);
      throw new Error(msg);
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime = MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported?.(t)) ?? "";
      mimeRef.current = mime;
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeRef.current || "audio/webm" });
        const reader = new FileReader();
        reader.onloadend = () => {
          const b64 = String(reader.result).split(",")[1] ?? "";
          // 释放麦克风
          streamRef.current?.getTracks().forEach((t) => t.stop());
          streamRef.current = null;
          recRef.current = null;
          // 只 resolve 当前 stop 调用（stopSeq 匹配才 resolve，防止快速 toggle 时 resolve 错误的 Promise）
          resolveRef.current?.({ b64, format: formatOf(mimeRef.current) });
          resolveRef.current = null;
        };
        reader.readAsDataURL(blob);
      };
      recRef.current = rec;
      rec.start();
      setRecording(true);
    } catch (e) {
      // 录音启动失败时释放麦克风，防止浏览器指示灯一直亮
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      const err = e as DOMException;
      const msg =
        err?.name === "NotAllowedError"
          ? "麦克风权限被拒绝，请在浏览器中允许"
          : err?.name === "NotFoundError"
            ? "没有找到麦克风设备"
            : "无法启动录音";
      setError(msg);
      throw e;
    }
  }, []);

  const stop = useCallback((): Promise<Recording> => {
    return new Promise((resolve) => {
      if (!recRef.current || recRef.current.state === "inactive") {
        setRecording(false);
        resolve({ b64: "", format: "webm" });
        return;
      }
      // 如果有未 resolve 的上一次 stop，先 resolve 空值（快速 toggle 保护）
      if (resolveRef.current) {
        resolveRef.current({ b64: "", format: "webm" });
      }
      resolveRef.current = resolve;
      stopSeqRef.current++;
      recRef.current.stop();
      setRecording(false);
    });
  }, []);

  return { recording, error, start, stop };
}
