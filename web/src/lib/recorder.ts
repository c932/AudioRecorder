// 浏览器录音 — MediaRecorder → base64（后端 ffmpeg 转 16kHz WAV 供 GOP/Whisper）。
// 每次录音新建 MediaStream：iOS/Safari 上复用同一 stream 创建第二个 MediaRecorder
// 会静默产出空数据（第一句正常、第二句"没录到声音"）。权限授予后 getUserMedia
// 不会重复弹窗，秒级返回，重建 stream 无感知。
import { useCallback, useEffect, useRef, useState } from "react";

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
  // 防竞态：start 去重（快速双击麦克风）、stop 幂等（快速双击停止时复用同一次结果，
  // 否则第二次 stop 会把第一次等待 onstop 的 resolve 用空数据立即兑现 → 误报"录音时长太短"）
  const startPromiseRef = useRef<Promise<void> | null>(null);
  const pendingStopRef = useRef<Promise<Recording> | null>(null);
  const recStartTsRef = useRef(0);
  const MIN_RECORD_MS = 300; // 短于此视为误触（点开始后立刻点停止）

  // 组件卸载时释放 stream
  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const start = useCallback(async () => {
    if (startPromiseRef.current) return startPromiseRef.current; // 快速双击麦克风：复用同一次启动
    const p = (async () => {
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
        // 释放旧 stream（若有），每次录音新建 —— 见文件头注释
        streamRef.current?.getTracks().forEach((t) => t.stop());
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
          // 录音结束即释放麦克风（下次录音重新获取）
          stream.getTracks().forEach((t) => t.stop());
          if (streamRef.current === stream) streamRef.current = null;
          const blob = new Blob(chunksRef.current, { type: mimeRef.current || "audio/webm" });
          const reader = new FileReader();
          reader.onloadend = () => {
            const b64 = String(reader.result).split(",")[1] ?? "";
            recRef.current = null;
            resolveRef.current?.({ b64, format: formatOf(mimeRef.current) });
            resolveRef.current = null;
          };
          reader.readAsDataURL(blob);
        };
        recRef.current = rec;
        recStartTsRef.current = Date.now();
        rec.start();
        setRecording(true);
      } catch (e) {
        // 录音启动失败时释放麦克风
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
    })().finally(() => { startPromiseRef.current = null; });
    startPromiseRef.current = p;
    return p;
  }, []);

  const stop = useCallback((): Promise<Recording> => {
    if (pendingStopRef.current) return pendingStopRef.current; // 快速双击停止：复用同一次结果
    const p = (async (): Promise<Recording> => {
      // start 还在进行时点了停止：等它完成再停（避免 recRef 未建立就停止 → 空数据）
      if (startPromiseRef.current) {
        try {
          await startPromiseRef.current;
        } catch {
          return { b64: "", format: "webm" };
        }
      }
      return await new Promise<Recording>((resolve) => {
        if (!recRef.current || recRef.current.state === "inactive") {
          setRecording(false);
          resolve({ b64: "", format: "webm" });
          return;
        }
        const tooShort = Date.now() - recStartTsRef.current < MIN_RECORD_MS;
        resolveRef.current = (r) => {
          // 误触（点开始后立刻点停止）：丢弃过短录音，避免拿空壳音频去评分
          resolve(tooShort ? { b64: "", format: r.format } : r);
        };
        stopSeqRef.current++;
        recRef.current.stop();
        setRecording(false);
      });
    })().finally(() => { pendingStopRef.current = null; });
    pendingStopRef.current = p;
    return p;
  }, []);

  return { recording, error, start, stop };
}
