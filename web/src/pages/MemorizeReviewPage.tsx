import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, type ReviewQuestion } from "../lib/api";
import { PageHeader, Spinner, ErrorText, btnPrimary } from "../components/ui";
import useStudyTracker from "../hooks/useStudyTracker";

type Phase = "setup" | "quiz" | "done";
type ReviewMode = "en2cn" | "cn2en" | "fill";

const MODES: { mode: ReviewMode; zh: string; desc: string }[] = [
  { mode: "en2cn", zh: "英翻中", desc: "看英文选中文释义" },
  { mode: "cn2en", zh: "中翻英", desc: "看中文选英文单词" },
  { mode: "fill", zh: "翻译填空", desc: "例句挖空打字填写" },
];

const BLANK_RE = /\(\d+\)_{4,}/g;

/** 学习中心复习测验 — 统一出题引擎（英翻中 / 中翻英四选一 + 例句填空）。 */
export default function MemorizeReviewPage() {
  const navigate = useNavigate();
  const loc = useLocation();
  const state = (loc.state ?? {}) as { key?: string; title?: string };
  const tracker = useStudyTracker("quiz", "中英互译");

  const snapshot = tracker.resumeSnapshot as {
    key?: string; mode?: ReviewMode; questions?: ReviewQuestion[];
    idx?: number; correctCount?: number;
  } | null;
  const restoreProgress = !!snapshot && !tracker.isReplay;

  const key = state.key ?? snapshot?.key;
  const [phase, setPhase] = useState<Phase>(
    (restoreProgress && snapshot?.questions?.length) ? "quiz" : "setup",
  );
  const [mode, setMode] = useState<ReviewMode>(snapshot?.mode ?? "en2cn");
  const [questions, setQuestions] = useState<ReviewQuestion[]>(
    restoreProgress ? (snapshot?.questions ?? []) : [],
  );
  const [idx, setIdx] = useState(restoreProgress ? (snapshot?.idx ?? 0) : 0);
  const [picked, setPicked] = useState<number | null>(null);
  const [inputs, setInputs] = useState<string[]>([]);
  const [qState, setQState] = useState<{ isCorrect: boolean; correctAnswer: string } | null>(null);
  const [correct, setCorrect] = useState(restoreProgress ? (snapshot?.correctCount ?? 0) : 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // 续学/再来一次：没有题目但有 key 时重新出题
  useEffect(() => {
    if (restoreProgress && key && !snapshot?.questions?.length) {
      start(mode).catch(() => {});
    }
    if (tracker.isReplay && key) {
      start(mode).catch(() => {});
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async (m: ReviewMode) => {
    if (!key) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.memorizeQuiz(key, m);
      if (r.questions.length === 0) {
        setError("没有生成任何题目");
        return;
      }
      setQuestions(r.questions);
      setMode(m);
      setIdx(0);
      setPicked(null);
      setInputs([]);
      setQState(null);
      setCorrect(0);
      setPhase("quiz");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const q = questions[idx];
  const blanks = q?.mode === "fill" ? (q.question_text.match(BLANK_RE)?.length ?? 1) : 0;

  const submit = async (userAnswer: string | string[]) => {
    if (!q || qState) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.memorizeAnswer(q, userAnswer);
      const correctAnswer = Array.isArray(r.correct_answer)
        ? r.correct_answer.join(" / ")
        : String(r.correct_answer);
      setQState({ isCorrect: r.is_correct, correctAnswer });
      if (r.is_correct) {
        const newCount = correct + 1;
        setCorrect(newCount);
        saveSnap(idx, newCount);
      } else {
        saveSnap(idx, correct);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // ── 学习记录：保存进度快照 ──
  const saveSnap = (curIdx: number, curCorrect: number) => {
    if (phase !== "quiz") return;
    const snap = { key, mode, questions, idx: curIdx, correctCount: curCorrect };
    tracker.setLatest(snap, `${curCorrect}/${curIdx}题正确`);
    tracker.saveSnapshot(snap, `${curCorrect}/${curIdx}题正确`);
  };

  const next = () => {
    setQState(null);
    setInputs([]);
    const nextIdx = idx + 1;
    if (nextIdx >= questions.length) {
      tracker.endSession(`测验完成：${correct}/${questions.length}题正确`);
      setPhase("done");
    } else {
      setIdx(nextIdx);
      saveSnap(nextIdx, correct);
    }
  };

  // ── Setup ──
  if (phase === "setup") {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title={state.title ?? "复习"} onBack={() => navigate("/memorize")} />
        <ErrorText text={error} />
        <div className="flex flex-col gap-3">
          <p className="text-ui font-bold">选择复习模式</p>
          <div className="grid grid-cols-3 gap-3">
            {MODES.map((m) => (
              <button
                key={m.mode}
                className={`rounded-xl p-4 border text-left transition-colors ${
                  mode === m.mode
                    ? "border-mango bg-mango/10"
                    : "border-desk-line bg-desk hover:bg-[#DDD7C6]"
                }`}
                onClick={() => setMode(m.mode)}
              >
                <p className="text-title font-bold">{m.zh}</p>
                <p className="text-body text-ink-soft">{m.desc}</p>
              </button>
            ))}
          </div>
        </div>
        <button className={btnPrimary} disabled={busy} onClick={() => start(mode)}>
          {busy ? "生成题目中…" : "开始复习"}
        </button>
        {busy && <p className="text-body text-ink-soft">AI 出题中，稍等片刻…</p>}
      </div>
    );
  }

  // ── Done ──
  if (phase === "done") {
    const pct = questions.length ? Math.round((correct / questions.length) * 100) : 0;
    return (
      <div className="flex flex-col gap-4 items-center pt-4">
        <PageHeader title="复习完成" onBack={() => navigate("/memorize")} />
        <p className="text-score font-extrabold text-mango-dk tabular-nums animate-pop">{pct}</p>
        <p className="text-ui text-ink-soft">
          答对 {correct} / {questions.length}
        </p>
        <div className="flex gap-2">
          <button className={btnPrimary} onClick={() => setPhase("setup")}>再来一轮</button>
        </div>
      </div>
    );
  }

  // ── Quiz ──
  if (!questions.length) return <Spinner label="加载题目…" />;
  const posExtra = q?.question_extra || "";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={`复习 ${idx + 1}/${questions.length}`} onBack={() => navigate("/memorize")} />
      <ErrorText text={error} />

      {/* 题目 */}
      <div className="bg-desk rounded-xl p-6 text-center border border-desk-line">
        {q.mode !== "fill" && (
          <p className="text-body text-ink-soft mb-2">
            {q.mode === "en2cn" ? "这个词是什么意思？" : "哪个英文单词是这个意思？"}
          </p>
        )}
        {q.mode === "fill" && blanks > 0 ? (
          <p className="text-title leading-relaxed">
            {q.question_text.split(BLANK_RE).map((part, i) => (
              <span key={i}>
                {part}
                {i < blanks && (
                  <input
                    value={inputs[i] ?? ""}
                    onChange={(e) => {
                      const v = [...inputs];
                      v[i] = e.target.value;
                      setInputs(v);
                    }}
                    disabled={!!qState}
                    aria-label={`第 ${i + 1} 空`}
                    className="inline-block w-24 sm:w-32 border-b-2 border-desk-line focus:border-mango bg-transparent text-center text-title font-bold outline-none mx-1 disabled:opacity-60"
                  />
                )}
              </span>
            ))}
          </p>
        ) : (
          <>
            <p className="text-header font-extrabold">{q.question_text}</p>
            {posExtra && <p className="text-body text-ink-soft mt-1">{posExtra}</p>}
          </>
        )}
        {q.mode === "fill" && q.chinese_hint && (
          <p className="text-body text-ink-soft mt-2">{q.chinese_hint}</p>
        )}
      </div>

      {q.mode !== "fill" ? (
        <>
          {/* 四选一选项 */}
          <div className="grid grid-cols-2 gap-3">
            {q.options?.map((opt, i) => {
              const isCorrect = qState && opt === qState.correctAnswer;
              const isPicked = picked === i;
              let cls = "border-desk-line bg-desk hover:bg-[#DDD7C6]";
              if (qState) {
                if (isCorrect) cls = "border-leaf bg-leaf/10 text-leaf";
                else if (isPicked) cls = "border-clay bg-clay/10 text-clay";
                else cls = "border-desk-line bg-desk opacity-50";
              }
              return (
                <button
                  key={i}
                  type="button"
                  disabled={qState !== null || busy}
                  onClick={async () => {
                    setPicked(i);
                    await submit(opt);
                  }}
                  className={`rounded-xl p-4 border text-left font-bold transition-colors ${cls}`}
                >
                  <span className="text-body text-ink-soft mr-2">{["A", "B", "C", "D"][i]}</span>
                  {opt}
                </button>
              );
            })}
          </div>
          {qState && (
            <div className="flex flex-col gap-2 items-center">
              <p className="text-ui font-bold">
                {qState.isCorrect ? "✅ 答对了！" : "❌ 再想想"}
              </p>
              <button className={btnPrimary} onClick={next}>
                {idx < questions.length - 1 ? "下一题" : "查看结果"}
              </button>
            </div>
          )}
        </>
      ) : qState ? (
        <div
          className={`rounded-xl p-4 border ${
            qState.isCorrect ? "bg-leaf-soft border-leaf text-leaf" : "bg-clay-soft border-clay text-clay"
          }`}
        >
          <p className="text-title font-bold">{qState.isCorrect ? "答对了！" : "再想想"}</p>
          <p className="text-ui">正确答案：{qState.correctAnswer}</p>
          <button className={`${btnPrimary} mt-3`} onClick={next}>
            {idx < questions.length - 1 ? "下一题" : "查看结果"}
          </button>
        </div>
      ) : (
        <button
          className={btnPrimary}
          disabled={
            busy ||
            Array.from({ length: blanks }, (_, i) => (inputs[i] ?? "").trim()).every((v) => !v)
          }
          onClick={() =>
            submit(blanks <= 1 ? inputs[0] ?? "" : inputs.slice(0, blanks))
          }
        >
          {busy ? "检查中…" : "提交答案"}
        </button>
      )}
    </div>
  );
}
