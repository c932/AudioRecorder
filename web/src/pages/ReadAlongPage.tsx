// 跟读教练 — 上传课文 → TTS 领读 → 跟读评分 → 低分重读 → 总结
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, type ReadAlongSegment, type ReadAlongSession,
  type ReadAlongScoreResult, type ReadAlongSummary,
} from "../lib/api";
import { useRecorder } from "../lib/recorder";
import { playSoundForScore, prefetchTts, speak, stopAudio } from "../lib/audio";
import RecordButton from "../components/RecordButton";
import ScoreResultView from "../components/ScoreResultView";
import {
  PageHeader, ProgressBar, Spinner, ErrorText,
  btnPrimary, btnSecondary, inputCls,
} from "../components/ui";
import { SpeakerIcon } from "../components/icons";

type Phase = "setup" | "readalong" | "summary";
type ReadState = "idle" | "playing" | "waiting" | "recording" | "scoring" | "scored";

const STORAGE_KEY = "readalong_text";

export default function ReadAlongPage() {
  const [phase, setPhase] = useState<Phase>("setup");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Setup — 从 localStorage 恢复
  const [rawText, setRawText] = useState(() => localStorage.getItem(STORAGE_KEY) || "");
  const [mode, setMode] = useState<"sentence" | "paragraph">("sentence");

  // Session
  const [session, setSession] = useState<ReadAlongSession | null>(null);
  const [segIdx, setSegIdx] = useState(0);

  // Read-along state machine
  const [readState, setReadState] = useState<ReadState>("idle");
  const [scoreResult, setScoreResult] = useState<ReadAlongScoreResult | null>(null);
  const [llmFeedback, setLlmFeedback] = useState("");

  // Summary
  const [summary, setSummary] = useState<ReadAlongSummary | null>(null);

  const { recording, error: recError, start, stop } = useRecorder();

  // 保存课文到 localStorage
  useEffect(() => {
    const t = setTimeout(() => {
      if (rawText.trim()) localStorage.setItem(STORAGE_KEY, rawText);
    }, 500);
    return () => clearTimeout(t);
  }, [rawText]);

  useEffect(() => () => stopAudio(), []);

  // Auto-scroll to current segment
  const segRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    segRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [segIdx]);

  // --- File upload handler ---
  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.readalongParseFile(file, true);
      setRawText(r.text);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // --- Play TTS for current segment ---
  const playCurrentSegment = useCallback(async (segments: ReadAlongSegment[], idx: number) => {
    if (idx >= segments.length) return;
    setReadState("playing");
    setScoreResult(null);
    setLlmFeedback("");
    try {
      await speak(segments[idx].text);
    } catch {
      // TTS 播放失败也继续
    }
    setReadState("waiting");
  }, []);

  // --- Start session ---
  const startSession = async () => {
    const text = rawText.trim();
    if (!text) {
      setError("请输入或上传课文内容");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.readalongStart(text, mode);
      setSession(r);
      setSegIdx(0);
      setScoreResult(null);
      setLlmFeedback("");
      setReadState("idle");
      setPhase("readalong");
      // 预取前几句 TTS 音频
      const texts = r.segments.slice(0, 4).map((s) => s.text);
      prefetchTts(texts);
      // Auto-play first segment TTS (延迟稍长确保 phase 切换完成)
      setTimeout(() => playCurrentSegment(r.segments, 0), 500);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // --- 点击句子切换 ---
  const clickSegment = (idx: number) => {
    if (!session || idx >= session.segments.length) return;
    // 停止当前播放/录音
    stopAudio();
    setSegIdx(idx);
    setScoreResult(null);
    setLlmFeedback("");
    // 播放选中句的标准音
    playCurrentSegment(session.segments, idx);
  };

  // --- Start recording ---
  const handleStartRecord = async () => {
    setReadState("recording");
    try {
      await start();
    } catch {
      setReadState("waiting");
    }
  };

  // --- Stop recording and score ---
  const handleStopRecord = async () => {
    const rec = await stop();
    if (!rec.b64 || !session) { setReadState("waiting"); return; }

    setReadState("scoring");
    setBusy(true);
    setError("");
    try {
      const r = await api.readalongScore(session.session_id, segIdx, rec.b64, rec.format);
      setScoreResult(r);
      setLlmFeedback(r.llm_feedback || "");
      setReadState("scored");

      playSoundForScore(r.score);

      // Speak LLM correction if available
      if (r.llm_feedback) {
        speak(r.llm_feedback).catch(() => {});
      }
    } catch (err) {
      setError((err as Error).message);
      setReadState("waiting");
    } finally {
      setBusy(false);
    }
  };

  // --- Advance to next segment ---
  const goNext = useCallback(() => {
    if (!session) return;
    const nextIdx = segIdx + 1;
    if (nextIdx >= session.total) {
      finishSession();
    } else {
      setSegIdx(nextIdx);
      const prefetchStart = nextIdx + 1;
      if (prefetchStart < session.segments.length) {
        const texts = session.segments
          .slice(prefetchStart, prefetchStart + 3)
          .map((s) => s.text);
        prefetchTts(texts);
      }
      playCurrentSegment(session.segments, nextIdx);
    }
  }, [session, segIdx, playCurrentSegment]);

  // --- Retry current segment ---
  const retrySegment = useCallback(() => {
    if (!session) return;
    setScoreResult(null);
    setLlmFeedback("");
    playCurrentSegment(session.segments, segIdx);
  }, [session, segIdx, playCurrentSegment]);

  // --- Re-listen TTS ---
  const reListen = useCallback(() => {
    if (!session) return;
    playCurrentSegment(session.segments, segIdx);
  }, [session, segIdx, playCurrentSegment]);

  // --- 拖拽排序 ---
  const dragIdx = useRef<number | null>(null);
  const handleDragStart = (idx: number) => { dragIdx.current = idx; };
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); };
  const handleDrop = (idx: number) => {
    if (!session || dragIdx.current === null || dragIdx.current === idx) return;
    const segs = [...session.segments];
    const [moved] = segs.splice(dragIdx.current, 1);
    segs.splice(idx, 0, moved);
    setSession({ ...session, segments: segs });
    // 如果当前句被移动，更新 segIdx
    if (segIdx === dragIdx.current) setSegIdx(idx);
    else if (dragIdx.current < segIdx && idx >= segIdx) setSegIdx(segIdx - 1);
    else if (dragIdx.current > segIdx && idx <= segIdx) setSegIdx(segIdx + 1);
    dragIdx.current = null;
  };

  // --- Finish session ---
  const finishSession = async () => {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      const s = await api.readalongSummary(session.session_id);
      setSummary(s);
      setPhase("summary");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const endSession = () => {
    stopAudio();
    finishSession();
  };

  // ==================== RENDER ====================

  if (phase === "setup") {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="跟读教练" />
        <ErrorText text={error} />
        <p className="text-ui text-ink-soft">
          上传课本图片或粘贴课文，AI 老师带你逐句朗读、评分、纠错。
        </p>

        {/* File upload */}
        <div className="bg-desk border border-desk-line rounded-xl p-4 flex flex-col gap-2">
          <p className="text-ui font-bold">上传课本（PDF / 图片）</p>
          <label
            htmlFor="readalong-file"
            className="bg-card border-2 border-dashed border-desk-line rounded-lg p-6 text-center cursor-pointer hover:border-mango transition-colors"
          >
            <p className="text-ui text-ink-soft">
              点击选择文件 或 拍照上传
            </p>
            <input
              id="readalong-file"
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif"
              onChange={handleFile}
              className="hidden"
            />
          </label>
        </div>

        {/* Text input */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <p className="text-ui font-bold">或者粘贴课文</p>
            {rawText.trim() && (
              <button
                className="text-body text-ink-soft/50 hover:text-clay transition-colors"
                onClick={() => { setRawText(""); localStorage.removeItem(STORAGE_KEY); }}
              >
                清除
              </button>
            )}
          </div>
          <textarea
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            placeholder="在这里粘贴英文课文内容..."
            rows={6}
            className={inputCls + " min-h-[120px]"}
          />
        </div>

        {/* Mode selection */}
        <div className="flex flex-col gap-2">
          <p className="text-ui font-bold">领读模式</p>
          <div className="flex gap-2">
            {(["sentence", "paragraph"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`px-4 py-2 rounded-lg text-ui font-bold border transition-colors ${
                  mode === m
                    ? "bg-mango border-mango-dk text-ink"
                    : "bg-card border-desk-line text-ink-soft hover:text-ink"
                }`}
              >
                {m === "sentence" ? "逐句领读" : "逐段领读"}
              </button>
            ))}
          </div>
        </div>

        <button className={btnPrimary} disabled={busy || !rawText.trim()} onClick={startSession}>
          {busy ? "AI 准备中…" : "开始跟读"}
        </button>
      </div>
    );
  }

  if (phase === "summary") {
    return (
      <div className="flex flex-col gap-4 py-6">
        <h1 className="text-section font-bold text-center">跟读完成</h1>
        {summary ? (
          <>
            <div className="text-center">
              <p className="text-score font-extrabold text-mango-dk tabular-nums animate-pop">
                {summary.avg_score}
              </p>
              <p className="text-body text-ink-soft">平均分</p>
            </div>
            <p className="text-ui text-ink-soft text-center">
              共 {summary.total_segments} {session?.mode === "paragraph" ? "段" : "句"}
              {summary.total_retries > 0 && ` · 重读 ${summary.total_retries} 次`}
            </p>
            <p className="text-ui text-center">{summary.summary}</p>

            {summary.weak_segments.length > 0 && (
              <div className="flex flex-col gap-2">
                <p className="text-ui font-bold text-clay">薄弱句</p>
                {summary.weak_segments.slice(0, 5).map((s, i) => (
                  <div
                    key={i}
                    className="bg-clay-soft border border-clay rounded-lg px-3 py-2 text-ui"
                  >
                    {s.text}
                    <span className="text-body text-ink-soft block">{s.translation}</span>
                  </div>
                ))}
              </div>
            )}

            {summary.weak_words.length > 0 && (
              <div className="flex flex-col gap-2">
                <p className="text-ui font-bold text-clay">需复习的词</p>
                <div className="flex flex-wrap gap-1.5">
                  {summary.weak_words.map((w, i) => (
                    <span
                      key={i}
                      className="text-body px-2 py-0.5 rounded bg-clay-soft border border-clay text-clay font-semibold"
                    >
                      {w}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <Spinner label="生成总结…" />
        )}
        <div className="flex gap-2 justify-center">
          <button className={btnSecondary} onClick={() => { setPhase("setup"); setSummary(null); setSession(null); }}>
            再练一篇
          </button>
        </div>
      </div>
    );
  }

  // ==================== readalong phase ====================
  const canRetry = scoreResult?.should_retry === true;
  const canAdvance = scoreResult && !canRetry;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="跟读教练" onBack={endSession} />

      {session && (
        <ProgressBar current={segIdx + 1} total={session.total} />
      )}

      {/* 课文显示区 — 支持点击切换 + 拖拽排序 */}
      <div className="bg-desk border border-desk-line rounded-xl p-4 max-h-[40vh] overflow-y-auto">
        {session?.segments.map((seg, i) => (
          <div
            key={i}
            ref={i === segIdx ? segRef : undefined}
            draggable
            onDragStart={() => handleDragStart(i)}
            onDragOver={handleDragOver}
            onDrop={() => handleDrop(i)}
            onClick={() => clickSegment(i)}
            className={`mb-3 last:mb-0 transition-colors cursor-pointer rounded-lg px-2 py-1 -mx-2 ${
              i < segIdx
                ? "text-ink-soft/60"
                : i === segIdx
                  ? "text-mango-dk bg-mango/5"
                  : "text-ink hover:bg-desk/50"
            }`}
          >
            <p className={`leading-relaxed break-words ${
              i === segIdx ? "font-bold text-title" : "text-ui"
            }`}>
              <span className="text-body text-ink-soft/30 mr-1 select-none">{i + 1}.</span>
              {seg.text}
            </p>
            {seg.translation && (
              <p className={`text-body mt-0.5 ${
                i === segIdx ? "text-ink-soft" : "text-ink-soft/50"
              }`}>
                {seg.translation}
              </p>
            )}
          </div>
        ))}
      </div>

      {/* 领读/听标准音 按钮 */}
      {readState !== "playing" && readState !== "recording" && readState !== "scoring" && (
        <button
          type="button"
          onClick={reListen}
          className="flex items-center gap-1.5 self-center px-4 py-2 rounded-lg bg-card border border-desk-line text-ui font-bold hover:border-mango transition-colors"
        >
          <SpeakerIcon className="w-4 h-4" />
          听标准音
        </button>
      )}

      {/* 播放中指示 */}
      {readState === "playing" && (
        <p className="text-ui text-ink-soft text-center animate-pulse">
          🔊 跟着老师读…
        </p>
      )}

      {/* ── 录音按钮 ── */}
      {(readState === "waiting" || readState === "recording") && (
        <RecordButton
          recording={recording}
          onStart={handleStartRecord}
          onStop={handleStopRecord}
          hint={recError || (readState === "waiting" ? "听完后点击开始跟读" : "朗读中，点击停止")}
        />
      )}

      {/* 评分中 */}
      {readState === "scoring" && (
        <p className="text-ui text-ink-soft text-center">评分中…</p>
      )}

      {/* ── 评分结果 ── */}
      {scoreResult && readState === "scored" && (
        <>
          <ScoreResultView result={scoreResult.details} />
          {llmFeedback && (
            <div className="bg-card border border-desk-line rounded-xl px-4 py-3">
              <p className="text-ui font-bold text-mango-dk">AI 纠错</p>
              <p className="text-ui">{llmFeedback}</p>
            </div>
          )}

          {canRetry && (
            <div className="bg-clay-soft border border-clay rounded-xl px-4 py-3">
              <p className="text-ui font-bold text-clay">
                还差一点点，再读一次吧！（第 {scoreResult.retry_count} 次）
              </p>
            </div>
          )}

          <div className="flex gap-2">
            {canRetry && (
              <button className={btnPrimary} onClick={retrySegment}>
                重新跟读
              </button>
            )}
            {canAdvance && (
              <button className={btnPrimary} onClick={goNext}>
                {segIdx + 1 >= (session?.total ?? 0) ? "看总结" : "下一句"}
              </button>
            )}
          </div>
        </>
      )}

      <ErrorText text={error} />

      <button
        className={`${btnSecondary} self-center text-body`}
        onClick={endSession}
        disabled={busy}
      >
        结束跟读
      </button>
    </div>
  );
}
