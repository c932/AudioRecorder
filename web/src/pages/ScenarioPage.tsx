import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  api, type ScenarioBank, type ScoreResult, type WordItem,
} from "../lib/api";
import { useRecorder } from "../lib/recorder";
import { playSoundForScore, speak, stopAudio } from "../lib/audio";
import RecordButton from "../components/RecordButton";
import ScoreResultView from "../components/ScoreResultView";
import GroupPicker from "../components/GroupPicker";
import {
  PageHeader, ProgressBar, ErrorText,
  btnPrimary, btnSecondary, inputCls,
} from "../components/ui";
import { SpeakerIcon } from "../components/icons";

interface Turn {
  role: "A" | "B";
  text: string;
  translation: string;
}

interface ChatEntry {
  turn: Turn;
  score?: number;
}

/** 情景会话 — A 角由应用朗读，B 角由学生跟读，逐句打分。 */
export default function ScenarioPage() {
  const location = useLocation();
  const stateItems = (location.state as { items?: WordItem[] } | null)?.items;
  const [phase, setPhase] = useState<"banks" | "chat" | "summary">("banks");
  const [banks, setBanks] = useState<ScenarioBank[] | null>(null);
  const [bank, setBank] = useState<ScenarioBank | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [turnCount, setTurnCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [script, setScript] = useState<Turn[]>([]);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [idx, setIdx] = useState(0);
  const [result, setResult] = useState<ScoreResult | null>(null);
  const [results, setResults] = useState<{ turn_idx: number; text: string; score: number }[]>([]);
  const [summary, setSummary] = useState("");
  const { recording, error: recError, start, stop } = useRecorder();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (stateItems && stateItems.length > 0) {
      // 从外部（速记页）传入了词条，自动生成对话
      setBusy(true);
      setError("");
      api
        .scenarioGenerateFromItems(stateItems, turnCount)
        .then((r) => {
          startSession(r.bank);
        })
        .catch((e) => setError((e as Error).message))
        .finally(() => setBusy(false));
    } else {
      api
        .scenarioBanks()
        .then((r) => setBanks(r.banks))
        .catch((e) => setError(e.message));
    }
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries, result]);

  useEffect(() => () => stopAudio(), []);

  // 驱动会话：A 角自动朗读并推进；B 角等学生录音
  useEffect(() => {
    if (phase !== "chat" || script.length === 0) return;
    if (idx >= script.length) {
      finish();
      return;
    }
    const turn = script[idx];
    if (entries.length === idx) {
      setEntries((e) => [...e, { turn }]);
    }
    if (turn.role === "A") {
      speak(turn.text)
        .catch(() => {})
        .finally(() => {
          window.setTimeout(() => setIdx((i) => i + 1), 250);
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, phase, script]);

  const finish = async () => {
    setBusy(true);
    try {
      const r = await api.scenarioSummary(
        results,
        bank?.name ?? "",
      );
      setSummary(r.summary);
      setPhase("summary");
    } catch (e) {
      setError((e as Error).message);
      setPhase("summary");
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    if (groups.length === 0) {
      setError("请先选择分组");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.scenarioGenerate(groups, turnCount);
      startSession(r.bank);
      setBanks(null);
      api.scenarioBanks().then((b) => setBanks(b.banks)).catch(() => {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const startSession = (b: ScenarioBank) => {
    const s = (b.script ?? []).map((t) => ({
      role: t.role as "A" | "B",
      text: t.text,
      translation: t.translation ?? "",
    }));
    if (s.length === 0) {
      setError("该题库没有对话内容");
      return;
    }
    setBank(b);
    setScript(s);
    setEntries([]);
    setResults([]);
    setIdx(0);
    setResult(null);
    setPhase("chat");
  };

  const curTurn = script[idx];

  const handleStop = async () => {
    if (!curTurn || curTurn.role !== "B") return;
    const rec = await stop();
    if (!rec.b64) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.score(rec.b64, rec.format, curTurn.text);
      setResult(r);
      setResults((res) => [
        ...res,
        { turn_idx: idx, text: curTurn.text, score: r.accuracy_score },
      ]);
      playSoundForScore(r.accuracy_score);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const confirmTurn = () => {
    // 把分数写到当前 B 气泡上，进入下一轮
    const score = result?.accuracy_score ?? 0;
    setEntries((es) =>
      es.map((e, i) => (i === es.length - 1 ? { ...e, score } : e)),
    );
    setResult(null);
    setIdx((i) => i + 1);
  };

  const skipTurn = () => {
    setIdx((i) => i + 1);
    setResult(null);
  };

  if (phase === "summary") {
    const avg = results.length
      ? Math.round(results.reduce((a, b) => a + b.score, 0) / results.length)
      : 0;
    return (
      <div className="flex flex-col gap-4 py-6">
        <h1 className="text-section font-bold text-center">会话结束</h1>
        <p className="text-score font-extrabold text-mango-dk tabular-nums text-center animate-pop">
          {avg}
        </p>
        <p className="text-ui text-ink-soft text-center">
          平均分 · {bank?.name ?? ""}
        </p>
        <div className="bg-desk border border-desk-line rounded-xl p-4">
          <p className="text-body text-ink-soft font-bold mb-1">AI 教练总结</p>
          <p className="text-ui leading-relaxed whitespace-pre-wrap">
            {summary || "这次会话的总结生成失败了，不过分数都在上面啦。"}
          </p>
        </div>
        <div className="flex gap-2 justify-center">
          <button className={btnSecondary} onClick={() => setPhase("banks")}>
            返回题库
          </button>
        </div>
      </div>
    );
  }

  if (phase === "chat") {
    const waitingB = curTurn?.role === "B" && !result;
    return (
      <div className="flex flex-col gap-3">
        <PageHeader title={bank?.name ?? "情景会话"} onBack={() => setPhase("banks")} />
        <ProgressBar current={Math.min(idx + 1, script.length)} total={script.length} />

        <div className="flex flex-col gap-2 overflow-y-auto">
          {entries.map((e, i) => (
            <div
              key={i}
              className={`max-w-[85%] rounded-xl px-4 py-2.5 ${
                e.turn.role === "A"
                  ? "self-start bg-desk border border-desk-line"
                  : "self-end bg-mango/90 text-ink"
              }`}
            >
              <p className="text-body text-ink-soft">
                {e.turn.role === "A" ? "对方" : "你"}
                {e.score !== undefined && (
                  <span
                    className={`ml-1 font-bold tabular-nums ${
                      e.score >= 80 ? "text-leaf" : e.score >= 60 ? "text-mango-dk" : "text-clay"
                    }`}
                  >
                    {e.score}
                  </span>
                )}
              </p>
              <p className="text-ui font-semibold break-words">{e.turn.text}</p>
              {e.turn.translation && (
                <p className="text-body text-ink-soft/80">{e.turn.translation}</p>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {result ? (
          <>
            <ScoreResultView result={result} />
            <div className="flex gap-2">
              <button className={btnSecondary} onClick={skipTurn}>
                跳过
              </button>
              <button className={btnPrimary} onClick={confirmTurn}>
                继续
              </button>
            </div>
          </>
        ) : waitingB ? (
          <>
            <div className="bg-card border border-desk-line rounded-xl p-3 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-body text-ink-soft">轮到你了，读这句：</p>
                <p className="text-ui font-bold truncate">{curTurn.text}</p>
              </div>
              <button
                type="button"
                onClick={() => speak(curTurn.text).catch(() => {})}
                aria-label="听这句"
                className="p-2 rounded-lg text-ink-soft hover:bg-desk hover:text-ink shrink-0"
              >
                <SpeakerIcon />
              </button>
            </div>
            <RecordButton
              recording={recording}
              disabled={busy}
              onStart={start}
              onStop={handleStop}
              hint={busy ? "评分中…" : recError || "点击开始朗读"}
            />
          </>
        ) : (
          <p className="text-body text-ink-soft text-center py-2">对方正在说…</p>
        )}
        <ErrorText text={error} />
      </div>
    );
  }

  // banks view
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="情景会话" />
      <ErrorText text={error} />

      <div className="flex flex-col gap-2">
        <p className="text-ui font-bold">生成新对话</p>
        <GroupPicker selected={groups} onChange={setGroups} />
        <div className="flex items-center gap-3">
          <label htmlFor="turn-count" className="text-ui font-bold">
            轮数
          </label>
          <input
            id="turn-count"
            type="number"
            min={4}
            max={40}
            value={turnCount}
            onChange={(e) =>
              setTurnCount(Math.max(4, Math.min(40, Number(e.target.value) || 10)))
            }
            className={inputCls + " w-24"}
          />
        </div>
        <button className={btnPrimary} disabled={busy} onClick={generate}>
          {busy ? "AI 编写对话中…（可能需要几分钟）" : "生成对话"}
        </button>
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-ui font-bold">已有对话</p>
        {!banks && <p className="text-body text-ink-soft">加载中…</p>}
        {banks?.length === 0 && (
          <p className="text-body text-ink-soft">还没有对话题库，先生成一个吧</p>
        )}
        {banks?.map((b) => (
          <button
            key={b.id}
            type="button"
            disabled={busy}
            onClick={() => startSession(b)}
            className="bg-desk border border-desk-line rounded-xl px-4 py-3 text-left hover:bg-[#DDD7C6] transition-colors"
          >
            <p className="text-ui font-bold">{b.name}</p>
            <p className="text-body text-ink-soft">
              {b.turn_count} 轮 · {b.created_at?.slice(0, 10)}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
