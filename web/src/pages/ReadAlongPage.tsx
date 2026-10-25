// 图书跟读 — 上传课文 → TTS 领读 → 跟读评分 → 低分重读 → 总结
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, type ReadAlongSegment, type ReadAlongSession,
  type ReadAlongScoreResult, type ReadAlongSummary,
} from "../lib/api";
import { useRecorder } from "../lib/recorder";
import useStudyTracker from "../hooks/useStudyTracker";
import { playSoundForScore, prefetchTts, speak, stopAudio, fetchTts } from "../lib/audio";
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
  const tracker = useStudyTracker("readalong", "图书跟读");

  const resumeSnap = tracker.resumeSnapshot as {
    sessionId?: string; segIdx?: number;
  } | null;
  const restoreProgress = !!resumeSnap && !tracker.isReplay;

  const [phase, setPhase] = useState<Phase>(restoreProgress && resumeSnap?.sessionId ? "readalong" : "setup");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Setup — 从 localStorage 恢复
  const [rawText, setRawText] = useState(() => localStorage.getItem(STORAGE_KEY) || "");
  const [mode, setMode] = useState<"sentence" | "paragraph">("sentence");

  // Session
  const [session, setSession] = useState<ReadAlongSession | null>(null);
  const [segIdx, setSegIdx] = useState(restoreProgress ? (resumeSnap?.segIdx ?? 0) : 0);

  // 续学：从后端恢复会话
  useEffect(() => {
    if (!restoreProgress || !resumeSnap?.sessionId) return;
    setBusy(true);
    setError("");
    api.readalongState(resumeSnap.sessionId)
      .then((r) => {
        const sess: ReadAlongSession = {
          session_id: r.session_id,
          segments: r.segments,
          total: r.total,
          mode: r.mode as "sentence" | "paragraph",
        };
        setSession(sess);
        setSegIdx(r.current_idx);
        // 预取当前句 TTS 并自动播放
        const curText = r.segments[r.current_idx]?.text;
        if (curText) {
          fetchTts(curText).catch(() => {});
        }
        prefetchTts(r.segments.slice(r.current_idx + 1, r.current_idx + 4).map((s) => s.text));
        playCurrentSegment(r.segments, r.current_idx);
      })
      .catch(() => {
        // 会话已过期，回到设置页
        setError("会话已过期，请重新开始");
        setPhase("setup");
      })
      .finally(() => setBusy(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Read-along state machine
  const [readState, setReadState] = useState<ReadState>("idle");
  const [scoreResult, setScoreResult] = useState<ReadAlongScoreResult | null>(null);
  const [llmFeedback, setLlmFeedback] = useState("");

  // Summary
  const [summary, setSummary] = useState<ReadAlongSummary | null>(null);

  const { recording, error: recError, start, stop } = useRecorder();

  // 防止录音/评分流程并发（双击、快速重复点击）
  const scoringRef = useRef(false);

  // 保存课文到 localStorage
  useEffect(() => {
    const t = setTimeout(() => {
      if (rawText.trim()) localStorage.setItem(STORAGE_KEY, rawText);
    }, 500);
    return () => clearTimeout(t);
  }, [rawText]);

  useEffect(() => () => {
    stopAudio();
    for (const u of previewRef.current) URL.revokeObjectURL(u);
  }, []);

  // Auto-scroll to current segment
  const segRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    segRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [segIdx]);

  // --- File upload handler（支持一次多选/连拍多张，按顺序合并成一篇课文） ---
  const [pickedPreviews, setPickedPreviews] = useState<string[]>([]);
  const previewRef = useRef<string[]>([]);
  previewRef.current = pickedPreviews;

  const handleFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // 允许再次选择同一文件
    if (!files.length) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.readalongParseFile(files, true);
      setRawText(r.text);
      // 显示已识别文件的缩略图（仅图片），方便确认拍的是哪几页
      for (const u of pickedPreviews) URL.revokeObjectURL(u);
      setPickedPreviews(files.filter((f) => f.type.startsWith("image/")).map((f) => URL.createObjectURL(f)));
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
      setPhase("readalong");
      // 预取第一句 TTS 音频并等待就绪，确保 play() 在用户手势上下文附近
      const firstText = r.segments[0]?.text;
      if (firstText) {
        try { await fetchTts(firstText); } catch { /* 预取失败也没关系 */ }
      }
      // 预取后续几句（不等待）
      prefetchTts(r.segments.slice(1, 4).map((s) => s.text));
      // 直接播放第一句（在点击手势上下文中，浏览器不会阻止）
      playCurrentSegment(r.segments, 0);
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
    if (readState !== "waiting") return; // 防止并发
    setReadState("recording");
    try {
      await start();
    } catch {
      setReadState("waiting");
    }
  };

  // --- Stop recording and score ---
  const handleStopRecord = async () => {
    // 锁在 await 之前设置：双击停止/评分中再点不会触发第二次评分
    if (scoringRef.current || readState !== "recording") return;
    scoringRef.current = true;
    const rec = await stop();
    if (!rec.b64 || !session) {
      // 录音数据为空（误触/太短）→ 给出明确提示而非静默返回
      if (!rec.b64 && session) setError("没录到声音，请点麦克风重新朗读一次");
      setReadState("waiting");
      scoringRef.current = false;
      return;
    }

    setReadState("scoring");
    setBusy(true);
    setError("");
    try {
      const r = await api.readalongScore(session.session_id, segIdx, rec.b64, rec.format);
      setScoreResult(r);
      setLlmFeedback(r.llm_feedback || "");
      setReadState("scored");

      playSoundForScore(r.score);

      // 学习记录：保存进度
      const snap = { sessionId: session?.session_id, segIdx };
      tracker.setLatest(snap, `跟读第${segIdx + 1}/${session?.total ?? "?"}句`);
      tracker.saveSnapshot(snap, `跟读第${segIdx + 1}/${session?.total ?? "?"}句`);

      // Speak LLM correction if available
      if (r.llm_feedback) {
        speak(r.llm_feedback).catch(() => {});
      }
    } catch (err) {
      setError((err as Error).message);
      setReadState("waiting");
    } finally {
      scoringRef.current = false;
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
      tracker.endSession(`跟读完成：${s.total_segments}句，平均分${s.avg_score}`);
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
        <PageHeader title="图书跟读" />
        <ErrorText text={error} />
        <p className="text-ui text-ink-soft">
          上传课本图片或粘贴课文，AI 老师带你逐句朗读、评分、纠错。
        </p>

        {/* File upload */}
        <div className="bg-desk border border-desk-line rounded-xl p-4 flex flex-col gap-2">
          <p className="text-ui font-bold">上传课本（PDF / 图片，支持一次多张）</p>
          <label
            htmlFor="readalong-file"
            className="bg-card border-2 border-dashed border-desk-line rounded-lg p-6 text-center cursor-pointer hover:border-mango transition-colors"
          >
            <p className="text-ui text-ink-soft">
              点击选择文件 或 拍照上传（可一次选多张，按顺序合成一篇课文）
            </p>
            <input
              id="readalong-file"
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif"
              multiple
              onChange={handleFiles}
              className="hidden"
            />
          </label>
          {busy && (
            <p className="text-ui text-mango-dk text-center">
              正在识别课文（多张图片可能需要十几秒）…
            </p>
          )}
          {pickedPreviews.length > 0 && (
            <div className="flex gap-2 overflow-x-auto">
              {pickedPreviews.map((u, i) => (
                <img
                  key={i}
                  src={u}
                  alt={`第${i + 1}张`}
                  className="h-16 w-24 object-cover rounded-lg border border-desk-line shrink-0"
                />
              ))}
            </div>
          )}
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
      <PageHeader title="图书跟读" onBack={endSession} />

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
