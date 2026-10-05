import { useState } from "react";
import { api, type QuizQuestion } from "../lib/api";
import GroupPicker from "../components/GroupPicker";
import {
  PageHeader, ProgressBar, Spinner, ErrorText,
  btnPrimary, inputCls,
} from "../components/ui";

const BLANK_RE = /\(\d+\)_{4,}/g;

interface QState {
  isCorrect: boolean;
  correctAnswer: string;
  chosen: string;
}

/** 中英互译测验 — zh2en 填空 / en2zh 选择。 */
export default function QuizPage() {
  const [groups, setGroups] = useState<string[]>([]);
  const [count, setCount] = useState(10);
  const [phase, setPhase] = useState<"setup" | "quiz" | "done">("setup");
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [idx, setIdx] = useState(0);
  const [qState, setQState] = useState<QState | null>(null);
  const [inputs, setInputs] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [correctCount, setCorrectCount] = useState(0);

  const start = async () => {
    if (groups.length === 0) {
      setError("请先选择分组");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.quizStart(groups, count);
      if (r.questions.length === 0) {
        setError("没有生成任何题目");
        return;
      }
      setQuestions(r.questions);
      setIdx(0);
      setQState(null);
      setInputs([]);
      setCorrectCount(0);
      setPhase("quiz");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const q = questions[idx];
  const blanks = q?.question_text?.match(BLANK_RE)?.length ?? 0;
  // zh2en 需要填的输入框数：填空题按空数，整词题（无空格占位）1 个
  const needInputs = q?.type === "zh2en" ? Math.max(1, blanks) : 0;

  const submit = async (userAnswer: string | string[]) => {
    if (!q || qState) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.quizAnswer(q, userAnswer);
      const correct = Array.isArray(r.correct_answer)
        ? r.correct_answer.join(" / ")
        : String(r.correct_answer);
      setQState({
        isCorrect: r.is_correct,
        correctAnswer: correct,
        chosen: Array.isArray(userAnswer) ? userAnswer.join(" / ") : userAnswer,
      });
      if (r.is_correct) setCorrectCount((c) => c + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const next = () => {
    setQState(null);
    setInputs([]);
    if (idx + 1 >= questions.length) setPhase("done");
    else setIdx((i) => i + 1);
  };

  if (phase === "setup") {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="中英互译" />
        <ErrorText text={error} />
        <div className="flex flex-col gap-2">
          <p className="text-ui font-bold">选择分组</p>
          <GroupPicker selected={groups} onChange={setGroups} />
        </div>
        <div className="flex items-center gap-3">
          <label htmlFor="quiz-count" className="text-ui font-bold">
            题数
          </label>
          <input
            id="quiz-count"
            type="number"
            min={1}
            max={50}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(50, Number(e.target.value) || 10)))}
            className={inputCls + " w-24"}
          />
        </div>
        <button className={btnPrimary} disabled={busy} onClick={start}>
          {busy ? "出题中…（AI 生成需要一点时间）" : "开始测验"}
        </button>
      </div>
    );
  }

  if (phase === "done") {
    const pct = questions.length
      ? Math.round((correctCount / questions.length) * 100)
      : 0;
    return (
      <div className="flex flex-col items-center gap-3 py-10">
        <h1 className="text-section font-bold">测验完成</h1>
        <p className="text-score font-extrabold text-mango-dk tabular-nums animate-pop">{pct}</p>
        <p className="text-ui text-ink-soft">
          答对 {correctCount} / {questions.length} 题
        </p>
        <div className="flex gap-2 mt-2">
          <button className={btnPrimary} onClick={() => setPhase("setup")}>
            再来一轮
          </button>
        </div>
      </div>
    );
  }

  if (!q) return <Spinner />;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="中英互译" />
      <ProgressBar current={idx + 1} total={questions.length} />
      <ErrorText text={error} />

      <div className="bg-desk border border-desk-line rounded-xl p-5 flex flex-col gap-3">
        {q.type === "en2zh" ? (
          <>
            <p className="text-title font-bold text-center break-words">{q.question_text}</p>
            <p className="text-body text-ink-soft text-center">这个词是什么意思？</p>
          </>
        ) : blanks > 0 ? (
          <>
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
            {q.chinese_hint && (
              <p className="text-body text-ink-soft text-center">提示：{q.chinese_hint}</p>
            )}
          </>
        ) : (
          <>
            <p className="text-title font-bold text-center break-words">{q.question_text}</p>
            <input
              value={inputs[0] ?? ""}
              onChange={(e) => setInputs([e.target.value])}
              disabled={!!qState}
              placeholder="输入英文"
              aria-label="输入英文答案"
              className={inputCls + " text-center text-title font-bold"}
            />
          </>
        )}
      </div>

      {q.type === "en2zh" ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {q.options?.map((opt, i) => {
            const isChosen = qState?.chosen === opt;
            const isCorrectOpt = qState && opt === qState.correctAnswer;
            return (
              <button
                key={i}
                type="button"
                disabled={!!qState || busy}
                onClick={() => submit(opt)}
                className={`rounded-xl px-4 py-3 text-left text-ui font-semibold border transition-colors ${
                  qState
                    ? isCorrectOpt
                      ? "bg-leaf-soft border-leaf text-leaf"
                      : isChosen
                        ? "bg-clay-soft border-clay text-clay"
                        : "bg-card border-desk-line text-ink-soft"
                    : "bg-card border-desk-line text-ink hover:border-mango"
                }`}
              >
                {opt}
              </button>
            );
          })}
        </div>
      ) : qState ? (
        <div
          className={`rounded-xl p-4 border animate-pop ${
            qState.isCorrect
              ? "bg-leaf-soft border-leaf text-leaf"
              : "bg-clay-soft border-clay text-clay"
          }`}
        >
          <p className="text-title font-bold">
            {qState.isCorrect ? "答对了！" : "再想想"}
          </p>
          <p className="text-ui">
            正确答案：{qState.correctAnswer}
          </p>
        </div>
      ) : (
        <button
          className={btnPrimary}
          disabled={
            busy ||
            Array.from({ length: needInputs }, (_, i) => (inputs[i] ?? "").trim()).every(
              (v) => !v,
            )
          }
          onClick={() =>
            submit(needInputs <= 1 ? inputs[0] ?? "" : inputs.slice(0, needInputs))
          }
        >
          {busy ? "检查中…" : "提交答案"}
        </button>
      )}

      {qState && (
        <button className={btnPrimary} onClick={next}>
          {idx + 1 >= questions.length ? "看成绩" : "下一题"}
        </button>
      )}
    </div>
  );
}
