import { useEffect, useRef, useState } from "react";
import type { TouchEvent } from "react";
import { useLocation } from "react-router-dom";
import { api, type ScoreResult, type WordItem } from "../lib/api";
import { useRecorder } from "../lib/recorder";
import { playSoundForScore, prefetchTts, speak, stopAudio } from "../lib/audio";
import RecordButton from "../components/RecordButton";
import ScoreResultView from "../components/ScoreResultView";
import {
  PageHeader, ProgressBar, Spinner, ErrorText,
  btnPrimary, btnSecondary,
} from "../components/ui";
import { BackIcon, ForwardIcon, SpeakerIcon } from "../components/icons";

/** 跟读练习 — 单词/句子大字卡 + 录音评分（GOP 音素级明细）。 */
export default function PracticePage() {
  const location = useLocation();
  const custom = (location.state as { items?: WordItem[] } | null)?.items;
  const [items, setItems] = useState<WordItem[] | null>(custom ?? null);
  const [idx, setIdx] = useState(0);
  const [result, setResult] = useState<ScoreResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [scores, setScores] = useState<number[]>([]);
  const [finished, setFinished] = useState(false);
  const { recording, error: recError, start, stop } = useRecorder();
  const touchX = useRef<number | null>(null);

  useEffect(() => {
    if (custom) return;
    api
      .practiceSession(20)
      .then((r) => setItems(r.items))
      .catch((e) => setError(e.message));
  }, [custom]);

  useEffect(() => () => stopAudio(), []);

  const word = items?.[idx];

  // 换词自动读一遍标准音
  useEffect(() => {
    if (word?.text) speak(word.text).catch(() => {});
  }, [word?.text]);

  // 预取当前 + 后面 3 个词的发音，翻页即播零等待
  useEffect(() => {
    if (!items) return;
    prefetchTts(items.slice(idx, idx + 4).map((w) => w.text));
  }, [items, idx]);

  const handleStop = async () => {
    if (!word) return;
    const rec = await stop();
    if (!rec.b64) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.score(rec.b64, rec.format, word.text);
      setResult(r);
      setScores((s) => [...s, r.accuracy_score]);
      playSoundForScore(r.accuracy_score);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** 左右翻页（清除当前评分，可自由往返）。 */
  const go = (delta: number) => {
    stopAudio();
    setResult(null);
    setIdx((i) => Math.min(Math.max(i + delta, 0), (items?.length ?? 1) - 1));
  };

  const next = () => {
    stopAudio();
    setResult(null);
    if (idx + 1 >= (items?.length ?? 0)) setFinished(true);
    else setIdx((i) => i + 1);
  };

  // 移动端：在卡片上左右滑动翻页
  const onTouchStart = (e: TouchEvent) => {
    touchX.current = e.touches[0]?.clientX ?? null;
  };
  const onTouchEnd = (e: TouchEvent) => {
    const x0 = touchX.current;
    touchX.current = null;
    if (x0 == null || !items) return;
    const dx = (e.changedTouches[0]?.clientX ?? x0) - x0;
    if (Math.abs(dx) < 50) return;
    const delta = dx < 0 ? 1 : -1; // 左滑下一个，右滑上一个
    if (idx + delta < 0 || idx + delta >= items.length) return;
    go(delta);
  };

  if (error && !items) return <ErrorText text={error} />;
  if (!items) return <Spinner label="准备练习…" />;
  if (items.length === 0) return <ErrorText text="没有可练习的词条，先去导入词库吧" />;

  if (finished) {
    const avg = scores.length
      ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
      : 0;
    return (
      <div className="flex flex-col items-center gap-3 py-10">
        <h1 className="text-section font-bold">练习完成</h1>
        <p className="text-score font-extrabold text-mango-dk tabular-nums animate-pop">
          {avg}
        </p>
        <p className="text-ui text-ink-soft">平均分 · 共 {scores.length} 题</p>
        <div className="flex gap-2 mt-2">
          <button className={btnSecondary} onClick={() => history.back()}>
            返回
          </button>
          <button className={btnPrimary} onClick={() => window.location.reload()}>
            再练一轮
          </button>
        </div>
      </div>
    );
  }

  const arrowCls =
    "shrink-0 p-3 rounded-lg bg-card border border-desk-line text-ink-soft " +
    "hover:border-mango hover:text-ink transition-colors " +
    "disabled:opacity-30 disabled:pointer-events-none";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="跟读练习" />
      <ProgressBar current={idx + 1} total={items.length} />

      <div
        className="flex items-center gap-2"
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
      >
        <button
          type="button"
          onClick={() => go(-1)}
          disabled={idx === 0}
          aria-label="上一个"
          className={arrowCls}
        >
          <BackIcon className="w-6 h-6" />
        </button>

        <div className="flex-1 min-w-0 bg-desk border border-desk-line rounded-xl p-6 flex flex-col items-center gap-2">
          <p className="text-word font-extrabold text-center break-words">{word!.text}</p>
          {word!.phonetic && <p className="text-phon text-ink-soft">{word!.phonetic}</p>}
          {word!.translation && <p className="text-ui text-ink-soft">{word!.translation}</p>}
          <button
            type="button"
            onClick={() => speak(word!.text).catch(() => {})}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-card border border-desk-line text-body font-bold hover:border-mango transition-colors"
          >
            <SpeakerIcon className="w-4 h-4" /> 听标准音
          </button>
        </div>

        <button
          type="button"
          onClick={() => go(1)}
          disabled={idx + 1 >= items.length}
          aria-label="下一个"
          className={arrowCls}
        >
          <ForwardIcon className="w-6 h-6" />
        </button>
      </div>

      {result ? (
        <>
          <ScoreResultView result={result} />
          <button className={btnPrimary} onClick={next}>
            {idx + 1 >= items.length ? "完成" : "下一个"}
          </button>
        </>
      ) : (
        <RecordButton
          recording={recording}
          disabled={busy}
          onStart={start}
          onStop={handleStop}
          hint={busy ? "评分中…" : recError || "先听标准音，再点击跟读"}
        />
      )}
      <ErrorText text={error} />
    </div>
  );
}
