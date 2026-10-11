import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { MemorizeEntry } from "../lib/api";
import { PageHeader, btnPrimary, btnSecondary } from "../components/ui";

/** 闪卡学习 — 三态翻转：英文 → 中文 → 英文+中文，左右箭头翻页。 */
export default function MemorizeStudyPage() {
  const navigate = useNavigate();
  const loc = useLocation();
  const state = (loc.state ?? {}) as { day?: number; title?: string; entries?: MemorizeEntry[] };

  const entries = state.entries ?? [];
  const [idx, setIdx] = useState(0);
  const [flip, setFlip] = useState(0); // 0=英文, 1=中文, 2=英文+中文

  if (!entries.length) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="学习" onBack={() => navigate("/memorize")} />
        <p className="text-body text-ink-soft">没有词条，请从分类速记选择一天。</p>
      </div>
    );
  }

  const e = entries[idx];
  const total = entries.length;

  const next = () => {
    if (idx < total - 1) {
      setIdx(idx + 1);
      setFlip(0);
    }
  };
  const prev = () => {
    if (idx > 0) {
      setIdx(idx - 1);
      setFlip(0);
    }
  };
  const click = () => setFlip((f) => (f + 1) % 3);

  return (
    <div className="flex flex-col gap-4 items-center">
      <PageHeader title={state.title ?? `Day ${state.day} 学习`} onBack={() => navigate("/memorize")} />

      {/* 进度 */}
      <p className="text-ui text-ink-soft">{idx + 1} / {total}</p>

      {/* 闪卡 */}
      <button
        type="button"
        onClick={click}
        className="w-full max-w-md min-h-[200px] bg-desk rounded-2xl border border-desk-line flex flex-col items-center justify-center gap-3 px-6 py-8 hover:bg-[#DDD7C6] active:bg-[#CFC8B5] transition-colors"
      >
        {flip === 0 && (
          <>
            <span className="text-header font-extrabold">{e.text}</span>
            {e.pos && <span className="text-body text-ink-soft">{e.pos}</span>}
            <span className="text-body text-ink-soft/50 mt-2">点击查看中文</span>
          </>
        )}
        {flip === 1 && (
          <>
            <span className="text-header font-extrabold">{e.translation}</span>
            <span className="text-body text-ink-soft/50 mt-2">点击查看全文</span>
          </>
        )}
        {flip === 2 && (
          <>
            <span className="text-header font-extrabold">{e.text}</span>
            {e.pos && <span className="text-body text-ink-soft">{e.pos}</span>}
            <span className="text-title font-bold mt-2">{e.translation}</span>
            <span className="text-body text-ink-soft/50 mt-2">点击进入下一个</span>
          </>
        )}
      </button>

      {/* 翻页 */}
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={prev}
          disabled={idx === 0}
          className={`${btnSecondary} disabled:opacity-30`}
        >
          ← 上一个
        </button>
        <button
          type="button"
          onClick={next}
          disabled={idx === total - 1}
          className={`${btnSecondary} disabled:opacity-30`}
        >
          下一个 →
        </button>
      </div>

      {idx === total - 1 && flip === 2 && (
        <button className={btnPrimary} onClick={() => navigate("/memorize")}>
          完成
        </button>
      )}
    </div>
  );
}
