import { useEffect, useState } from "react";
import { api, type OralBank, type OralSentence, type ScoreResult } from "../lib/api";
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

/** 口语朗读测试 — 从题库选句，逐句朗读评分。 */
export default function OralTestPage() {
  const [phase, setPhase] = useState<"banks" | "test" | "done">("banks");
  const [banks, setBanks] = useState<OralBank[] | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [count, setCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sentences, setSentences] = useState<OralSentence[]>([]);
  const [idx, setIdx] = useState(0);
  const [result, setResult] = useState<ScoreResult | null>(null);
  const [scores, setScores] = useState<number[]>([]);
  const { recording, error: recError, start, stop } = useRecorder();

  useEffect(() => {
    api
      .oralBanks()
      .then((r) => setBanks(r.banks))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => () => stopAudio(), []);

  const generate = async () => {
    if (groups.length === 0) {
      setError("请先选择分组");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.oralGenerate(groups, count);
      await startTest(r.bank.id);
      setBanks(null);
      api.oralBanks().then((b) => setBanks(b.banks)).catch(() => {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const startTest = async (bankId: string) => {
    setBusy(true);
    setError("");
    try {
      const r = await api.oralBankSentences(bankId);
      if (r.sentences.length === 0) {
        setError("该题库没有句子");
        return;
      }
      setSentences(r.sentences);
      setIdx(0);
      setResult(null);
      setScores([]);
      setPhase("test");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const sentence = sentences[idx];

  const handleStop = async () => {
    if (!sentence) return;
    const rec = await stop();
    if (!rec.b64) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.score(rec.b64, rec.format, sentence.text);
      setResult(r);
      setScores((s) => [...s, r.accuracy_score]);
      playSoundForScore(r.accuracy_score);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const next = () => {
    stopAudio();
    setResult(null);
    if (idx + 1 >= sentences.length) setPhase("done");
    else setIdx((i) => i + 1);
  };

  if (phase === "done") {
    const avg = scores.length
      ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
      : 0;
    const weak = sentences
      .map((s, i) => ({ s, score: scores[i] }))
      .filter((x) => x.score !== undefined && x.score < 80);
    return (
      <div className="flex flex-col gap-4 py-6">
        <h1 className="text-section font-bold text-center">测试完成</h1>
        <p className="text-score font-extrabold text-mango-dk tabular-nums text-center animate-pop">
          {avg}
        </p>
        <p className="text-ui text-ink-soft text-center">平均分 · 共 {scores.length} 句</p>
        {weak.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-ui font-bold">这些句子可以再练练：</p>
            {weak.map((w, i) => (
              <div
                key={i}
                className="bg-card border-l-4 border-clay rounded-lg px-3 py-2 text-ui"
              >
                {w.s.text} <span className="text-clay font-bold tabular-nums">{w.score}</span>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-2 justify-center">
          <button className={btnSecondary} onClick={() => setPhase("banks")}>
            返回题库
          </button>
        </div>
      </div>
    );
  }

  if (phase === "test") {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="口语测试" onBack={() => setPhase("banks")} />
        <ProgressBar current={idx + 1} total={sentences.length} />

        <div className="bg-desk border border-desk-line rounded-xl p-5 flex flex-col items-center gap-2">
          <p className="text-title font-bold text-center leading-relaxed break-words">
            {sentence?.text}
          </p>
          {sentence?.translation && (
            <p className="text-body text-ink-soft text-center">{sentence.translation}</p>
          )}
          <button
            type="button"
            onClick={() => sentence && speak(sentence.text).catch(() => {})}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-card border border-desk-line text-body font-bold hover:border-mango transition-colors"
          >
            <SpeakerIcon className="w-4 h-4" /> 听标准音
          </button>
        </div>

        {result ? (
          <>
            <ScoreResultView result={result} />
            <button className={btnPrimary} onClick={next}>
              {idx + 1 >= sentences.length ? "看成绩" : "下一句"}
            </button>
          </>
        ) : (
          <RecordButton
            recording={recording}
            disabled={busy}
            onStart={start}
            onStop={handleStop}
            hint={busy ? "评分中…" : recError || "听标准音后，点击朗读"}
          />
        )}
        <ErrorText text={error} />
      </div>
    );
  }

  // banks view
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="口语测试" />
      <ErrorText text={error} />

      <div className="flex flex-col gap-2">
        <p className="text-ui font-bold">生成新题库</p>
        <GroupPicker selected={groups} onChange={setGroups} />
        <div className="flex items-center gap-3">
          <label htmlFor="oral-count" className="text-ui font-bold">
            句数
          </label>
          <input
            id="oral-count"
            type="number"
            min={1}
            max={30}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(30, Number(e.target.value) || 10)))}
            className={inputCls + " w-24"}
          />
        </div>
        <button className={btnPrimary} disabled={busy} onClick={generate}>
          {busy ? "AI 出题中…（可能需要几分钟）" : "生成题库"}
        </button>
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-ui font-bold">已有题库</p>
        {!banks && <p className="text-body text-ink-soft">加载中…</p>}
        {banks?.length === 0 && (
          <p className="text-body text-ink-soft">还没有题库，先生成一个吧</p>
        )}
        {banks?.map((b) => (
          <button
            key={b.id}
            type="button"
            disabled={busy}
            onClick={() => startTest(b.id)}
            className="bg-desk border border-desk-line rounded-xl px-4 py-3 text-left hover:bg-[#DDD7C6] transition-colors"
          >
            <p className="text-ui font-bold">{b.name}</p>
            <p className="text-body text-ink-soft">
              {b.sentence_count ?? b.sentences?.length ?? 0} 句
              {b.created_at ? ` · ${b.created_at.slice(0, 10)}` : ""}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
