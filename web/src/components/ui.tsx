// 共享小部件 — 按钮、页头、进度条、加载、错误提示。
import { useNavigate } from "react-router-dom";
import { BackIcon } from "./icons";

export const btnPrimary =
  "bg-mango hover:bg-mango-dk text-ink font-bold rounded-xl px-5 py-2.5 text-ui disabled:opacity-40 disabled:pointer-events-none transition-colors";
export const btnSecondary =
  "bg-desk hover:bg-[#DDD7C6] text-ink border border-desk-line font-semibold rounded-xl px-5 py-2.5 text-ui disabled:opacity-40 disabled:pointer-events-none transition-colors";
export const inputCls =
  "w-full bg-card border border-desk-line rounded-lg px-3 py-2 text-ui text-ink placeholder:text-ink-soft/60 focus:border-mango focus:outline-none";

export function PageHeader({
  title,
  backTo,
  onBack,
}: {
  title: string;
  backTo?: string;
  onBack?: () => void;
}) {
  const navigate = useNavigate();
  return (
    <div className="flex items-center gap-2 mb-4">
      {(backTo || onBack) && (
        <button
          type="button"
          onClick={() => (onBack ? onBack() : navigate(backTo!))}
          aria-label="返回"
          className="p-2 -ml-2 rounded-lg text-ink-soft hover:bg-desk hover:text-ink transition-colors"
        >
          <BackIcon />
        </button>
      )}
      <h1 className="text-section font-bold">{title}</h1>
    </div>
  );
}

export function ProgressBar({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 h-2 bg-desk rounded-lg overflow-hidden">
        <div
          className="h-full bg-mango rounded-lg transition-all duration-300"
          style={{ width: `${total > 0 ? Math.min(100, (current / total) * 100) : 0}%` }}
        />
      </div>
      <span className="text-body text-ink-soft font-bold tabular-nums shrink-0">
        {current}/{total}
      </span>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-ink-soft">
      <div className="w-8 h-8 border-[3px] border-desk-line border-t-mango rounded-full animate-spin" aria-hidden />
      {label && <p className="text-ui font-semibold">{label}</p>}
    </div>
  );
}

export function ErrorText({ text }: { text: string }) {
  if (!text) return null;
  return <p className="text-body text-clay font-semibold text-center">{text}</p>;
}
