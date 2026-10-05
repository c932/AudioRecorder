// 录音按钮 — 全应用唯一的圆形元素（88px，物理麦克风隐喻）。
// 空闲：MANGO + 麦克风图标；录音中：CLAY + 方块停止图标 + 脉冲环。
import { MicIcon, StopIcon } from "./icons";

interface Props {
  recording: boolean;
  disabled?: boolean;
  onStart: () => void;
  onStop: () => void;
  hint?: string;
}

export default function RecordButton({ recording, disabled, onStart, onStop, hint }: Props) {
  return (
    <div className="flex flex-col items-center gap-2 py-2">
      <button
        type="button"
        disabled={disabled}
        onClick={recording ? onStop : onStart}
        aria-label={recording ? "停止录音" : "开始录音"}
        className={`relative w-[88px] h-[88px] rounded-full flex items-center justify-center transition-colors disabled:opacity-40 disabled:pointer-events-none ${
          recording ? "bg-clay" : "bg-mango hover:bg-mango-dk active:bg-mango-dk"
        }`}
      >
        {recording && (
          <span
            className="absolute inset-0 rounded-full bg-clay animate-pulse-ring"
            aria-hidden
          />
        )}
        {recording ? (
          <StopIcon className="relative w-8 h-8 text-white" />
        ) : (
          <MicIcon className="relative w-10 h-10 text-ink" />
        )}
      </button>
      {hint && <p className="text-body text-ink-soft font-semibold">{hint}</p>}
    </div>
  );
}
