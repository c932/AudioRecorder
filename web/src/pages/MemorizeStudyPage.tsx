import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { MemorizeEntry } from "../lib/api";
import { PageHeader, btnPrimary, btnSecondary } from "../components/ui";
import { speak, prefetchTts } from "../lib/audio";
import useStudyTracker from "../hooks/useStudyTracker";

/** 闪卡学习 — 三态翻转：英文 → 中文 → 英文+中文，点三次自动下一个，带 TTS 发音。 */
export default function MemorizeStudyPage() {
  const navigate = useNavigate();
  const loc = useLocation();
  const state = (loc.state ?? {}) as { day?: number; title?: string; entries?: MemorizeEntry[] };
  const tracker = useStudyTracker("memorize", "分类速记");

  const resumeSnap = tracker.resumeSnapshot as {
    day?: number; idx?: number;
  } | null;

  const entries = state.entries ?? [];
  const [idx, setIdx] = useState(resumeSnap?.idx ?? 0);
  const [flip, setFlip] = useState(0); // 0=英文, 1=中文, 2=英文+中文

  // 预取当前及后续几个词的发音
  if (entries.length > 0) {
    const upcoming = entries.slice(idx, idx + 5).map((e) => e.text);
    prefetchTts(upcoming);
  }

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

  const goToNext = () => {
    if (idx < total - 1) {
      const nextIdx = idx + 1;
      setIdx(nextIdx);
      setFlip(0);
      const snap = { day: state.day, idx: nextIdx };
      tracker.setLatest(snap, `速记Day${state.day}：第${nextIdx + 1}/${total}词`);
      tracker.saveSnapshot(snap, `速记Day${state.day}：第${nextIdx + 1}/${total}词`);
    }
  };
  const prev = () => {
    if (idx > 0) {
      const prevIdx = idx - 1;
      setIdx(prevIdx);
      setFlip(0);
      const snap = { day: state.day, idx: prevIdx };
      tracker.setLatest(snap, `速记Day${state.day}：第${prevIdx + 1}/${total}词`);
      tracker.saveSnapshot(snap, `速记Day${state.day}：第${prevIdx + 1}/${total}词`);
    }
  };

  // 点击三次后自动切换到下一个词
  const click = () => {
    if (flip === 2) {
      // 第三次点击 → 下一个
      goToNext();
    } else {
      setFlip((f) => f + 1);
    }
  };

  // 发音按钮
  const playSound = (ev: React.MouseEvent) => {
    ev.stopPropagation();
    speak(e.text);
  };

  const handleFinish = () => {
    tracker.endSession(`速记Day${state.day}完成：${total}词`);
    navigate("/memorize");
  };

  return (
    <div className="flex flex-col gap-4 items-center">
      <PageHeader title={state.title ?? `Day ${state.day} 学习`} onBack={() => navigate("/memorize")} />

      {/* 进度 */}
      <p className="text-ui text-ink-soft">{idx + 1} / {total}</p>

      {/* 闪卡 */}
      <button
        type="button"
        onClick={click}
        className="w-full max-w-md min-h-[200px] bg-desk rounded-2xl border border-desk-line flex flex-col items-center justify-center gap-3 px-6 py-8 hover:bg-[#DDD7C6] active:bg-[#CFC8B5] transition-colors relative"
      >
        {flip === 0 && (
          <>
            <span className="text-header font-extrabold">{e.text}</span>
            {e.pos && <span className="text-body text-ink-soft">{e.pos}</span>}
            {/* 发音按钮 */}
            <button
              type="button"
              onClick={playSound}
              className="mt-2 px-3 py-1.5 rounded-lg bg-card border border-desk-line text-ui font-bold text-mango-dk hover:bg-mango/10 transition-colors"
            >
              🔊 发音
            </button>
            <span className="text-body text-ink-soft/50 mt-1">点击查看中文</span>
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
            {/* 发音按钮 */}
            <button
              type="button"
              onClick={playSound}
              className="mt-2 px-3 py-1.5 rounded-lg bg-card border border-desk-line text-ui font-bold text-mango-dk hover:bg-mango/10 transition-colors"
            >
              🔊 发音
            </button>
            <span className="text-title font-bold mt-2">{e.translation}</span>
            <span className="text-body text-ink-soft/50 mt-1">
              {idx < total - 1 ? "点击进入下一个" : "点击完成"}
            </span>
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
          onClick={goToNext}
          disabled={idx === total - 1}
          className={`${btnSecondary} disabled:opacity-30`}
        >
          下一个 →
        </button>
      </div>

      {idx === total - 1 && flip === 2 && (
        <button className={btnPrimary} onClick={handleFinish}>
          完成
        </button>
      )}
    </div>
  );
}
