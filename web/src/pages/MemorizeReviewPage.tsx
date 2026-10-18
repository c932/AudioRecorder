import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, type MemorizeQuizQuestion } from "../lib/api";
import { PageHeader, Spinner, ErrorText, btnPrimary } from "../components/ui";

type Phase = "setup" | "quiz" | "done";

/** 复习测验 — 英翻中 / 中翻英四选一，LLM 生成混淆选项。 */
export default function MemorizeReviewPage() {
  const navigate = useNavigate();
  const loc = useLocation();
  const state = (loc.state ?? {}) as { key?: string; title?: string };

  const [phase, setPhase] = useState<Phase>("setup");
  const [mode, setMode] = useState<"en2cn" | "cn2en">("en2cn");
  const [questions, setQuestions] = useState<MemorizeQuizQuestion[]>([]);
  const [idx, setIdx] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [correct, setCorrect] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const start = async () => {
    if (!state.key) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.memorizeQuiz(state.key, mode);
      setQuestions(r.questions);
      setIdx(0);
      setPicked(null);
      setCorrect(0);
      setPhase("quiz");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const pick = (i: number) => {
    if (picked !== null) return;
    setPicked(i);
    if (i === questions[idx].answer_index) {
      setCorrect((c) => c + 1);
    }
  };

  const next = () => {
    if (idx < questions.length - 1) {
      setIdx(idx + 1);
      setPicked(null);
    } else {
      setPhase("done");
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
          <div className="grid grid-cols-2 gap-3">
            <button
              className={`rounded-xl p-4 border text-left transition-colors ${
                mode === "en2cn"
                  ? "border-mango bg-mango/10"
                  : "border-desk-line bg-desk hover:bg-[#DDD7C6]"
              }`}
              onClick={() => setMode("en2cn")}
            >
              <p className="text-title font-bold">英翻中</p>
              <p className="text-body text-ink-soft">看英文选中文释义</p>
            </button>
            <button
              className={`rounded-xl p-4 border text-left transition-colors ${
                mode === "cn2en"
                  ? "border-mango bg-mango/10"
                  : "border-desk-line bg-desk hover:bg-[#DDD7C6]"
              }`}
              onClick={() => setMode("cn2en")}
            >
              <p className="text-title font-bold">中翻英</p>
              <p className="text-body text-ink-soft">看中文选英文单词</p>
            </button>
          </div>
        </div>
        <button className={btnPrimary} disabled={busy} onClick={start}>
          {busy ? "生成题目中…" : "开始复习"}
        </button>
        {busy && <p className="text-body text-ink-soft">LLM 正在生成混淆选项…</p>}
      </div>
    );
  }

  // ── Done ──
  if (phase === "done") {
    const pct = Math.round((correct / questions.length) * 100);
    return (
      <div className="flex flex-col gap-4 items-center pt-4">
        <PageHeader title="复习完成" onBack={() => navigate("/memorize")} />
        <div className="text-center">
          <p className="text-header font-extrabold">{pct} 分</p>
          <p className="text-ui text-ink-soft mt-1">
            答对 {correct} / {questions.length}
          </p>
        </div>
        <button className={btnPrimary} onClick={() => setPhase("setup")}>再来一轮</button>
      </div>
    );
  }

  // ── Quiz ──
  if (!questions.length) return <Spinner label="加载题目…" />;
  const q = questions[idx];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={`复习 ${idx + 1}/${questions.length}`} onBack={() => navigate("/memorize")} />

      {/* 题目 */}
      <div className="bg-desk rounded-xl p-6 text-center border border-desk-line">
        <p className="text-body text-ink-soft mb-2">
          {q.direction === "en2cn" ? "这个词是什么意思？" : "哪个英文单词是这个意思？"}
        </p>
        <p className="text-header font-extrabold">{q.question}</p>
        {q.question_extra && (
          <p className="text-body text-ink-soft mt-1">{q.question_extra}</p>
        )}
      </div>

      {/* 选项 */}
      <div className="grid grid-cols-2 gap-3">
        {q.options.map((opt, i) => {
          const isCorrect = i === q.answer_index;
          const isPicked = i === picked;
          let cls = "border-desk-line bg-desk hover:bg-[#DDD7C6]";
          if (picked !== null) {
            if (isCorrect) cls = "border-leaf bg-leaf/10 text-leaf";
            else if (isPicked) cls = "border-clay bg-clay/10 text-clay";
            else cls = "border-desk-line bg-desk opacity-50";
          }
          return (
            <button
              key={i}
              type="button"
              disabled={picked !== null}
              onClick={() => pick(i)}
              className={`rounded-xl p-4 border text-left font-bold transition-colors ${cls}`}
            >
              <span className="text-body text-ink-soft mr-2">{["A", "B", "C", "D"][i]}</span>
              {opt}
            </button>
          );
        })}
      </div>

      {/* 反馈 + 下一题 */}
      {picked !== null && (
        <div className="flex flex-col gap-2 items-center">
          <p className="text-ui font-bold">
            {picked === q.answer_index ? "✅ 答对了！" : "❌ 再想想"}
          </p>
          <button className={btnPrimary} onClick={next}>
            {idx < questions.length - 1 ? "下一题" : "查看结果"}
          </button>
        </div>
      )}
    </div>
  );
}
