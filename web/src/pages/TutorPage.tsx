// AI 家教 — 有状态多轮会话。action 决定输入模式：
// teach_word/ask_repeat → 跟读评分（GOP）；ask_meaning/ask_sentence/dialogue →
// 语音/文本回答（ASR）；ask_choice → 选择题；feedback → 纯气泡；session_end → 总结。
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  api, type TutorAction, type TutorState, type WordItem,
} from "../lib/api";
import { useRecorder } from "../lib/recorder";
import { speak, speakViaToken, stopAudio } from "../lib/audio";
import RecordButton from "../components/RecordButton";
import GroupPicker from "../components/GroupPicker";
import {
  PageHeader, ProgressBar, Spinner, ErrorText,
  btnPrimary, btnSecondary, inputCls,
} from "../components/ui";
import { SpeakerIcon } from "../components/icons";

interface Bubble {
  role: "ai" | "user";
  text: string;
  score?: number;
}

type Mode = "gop" | "asr" | "choice" | null;

/** 与桌面版 tutor_page 相同的正确项判定：匹配词/释义，兜底第一项。 */
function findCorrectOption(options: string[], word: string, translation: string): string {
  for (const opt of options) {
    const clean = opt.replace(/^[A-G][.、]\s*/, "").trim();
    if (
      clean.toLowerCase() === word.toLowerCase() ||
      clean === translation ||
      (translation && (translation.includes(clean) || clean.includes(translation)))
    ) {
      return opt;
    }
  }
  return options[0];
}

export default function TutorPage() {
  const location = useLocation();
  const stateItems = (location.state as { items?: WordItem[] } | null)?.items;
  const [phase, setPhase] = useState<"setup" | "chat" | "summary">(
    stateItems && stateItems.length > 0 ? "chat" : "setup",
  );
  const [group, setGroup] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [state, setState] = useState<TutorState | null>(null);
  const [lastAction, setLastAction] = useState<TutorAction | null>(null);
  const [mode, setMode] = useState<Mode>(null);
  const [options, setOptions] = useState<string[]>([]);
  const [correctOption, setCorrectOption] = useState("");
  const [text, setText] = useState("");
  const [summary, setSummary] = useState<{
    topic: string; total_words: number; mastered: number; weak_words: string[];
  } | null>(null);
  const { recording, start, stop } = useRecorder();
  const bottomRef = useRef<HTMLDivElement>(null);
  // 自动录音计时器引用
  const autoRecordTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 启动时从配置加载已保存的分组
  useEffect(() => {
    api.config().then((c) => {
      const saved = (c["active_groups"] as string[]) ?? [];
      if (saved.length > 0) setGroup(saved.slice(-1)); // 家教单选，取最后一个
    }).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [bubbles, lastAction]);

  useEffect(() => {
    // 从速记页等外部跳入时，自动启动会话
    if (stateItems && stateItems.length > 0 && phase === "chat" && bubbles.length === 0 && !busy) {
      startSession(stateItems);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stateItems, phase]);

  useEffect(() => () => {
    stopAudio();
    if (autoRecordTimer.current) clearTimeout(autoRecordTimer.current);
  }, []);

  /** 播放 TTS：优先用后端预合成 token，否则回退到前端请求合成 */
  const playTts = async (action: TutorAction): Promise<void> => {
    if (action.tts_token) {
      return speakViaToken(action.tts_token);
    }
    const ttsText = action.tts_text || action.text;
    if (ttsText) {
      return speak(ttsText);
    }
    return Promise.resolve();
  };

  /** TTS 播放完后自动开始录音（参照情景会话模式） */
  const scheduleAutoRecord = (m: Mode) => {
    if (autoRecordTimer.current) clearTimeout(autoRecordTimer.current);
    if (m === "gop" || m === "asr") {
      autoRecordTimer.current = setTimeout(() => {
        start().catch(() => {});
      }, 600);
    }
  };

  const applyActions = async (actions: TutorAction[], st: TutorState, extra?: Bubble) => {
    const newBubbles: Bubble[] = extra ? [extra] : [];
    let last: TutorAction | null = null;
    for (const a of actions) {
      newBubbles.push({ role: "ai", text: a.text });
      last = a;
    }
    setBubbles((b) => [...b, ...newBubbles]);
    setState(st);
    setLastAction(last);
    setOptions([]);
    setCorrectOption("");

    // 输入模式：优先看 action（明确的提问类型）；feedback 等非输入 action
    // 按 phase 兜底——发音重试的鼓励 feedback 后学生还要继续跟读。
    const act = last?.action;
    const opts = act === "ask_choice" ? last?.options ?? [] : [];
    let m: Mode;
    if (act === "teach_word" || act === "ask_repeat") m = "gop";
    else if (act === "ask_meaning" || act === "ask_sentence" || act === "dialogue") m = "asr";
    else if (opts.length > 0) m = "choice";
    else {
      switch (st.phase) {
        case "WORD_LISTEN":
        case "RETRY_PHASE":
          m = "gop";
          break;
        case "WORD_MEANING":
        case "WORD_CHOICE":
        case "SENTENCE_MAKING":
        case "MICRO_DIALOGUE":
          m = "asr";
          break;
        default:
          m = null;
      }
    }
    setMode(m);
    if (m === "choice") {
      setOptions(opts);
      setCorrectOption(findCorrectOption(opts, st.word, st.translation));
    }
    // 播放 TTS，播完后自动开始录音
    if (last) {
      try {
        await playTts(last);
        // TTS 播完，自动开始录音
        scheduleAutoRecord(m);
      } catch {
        // TTS 失败也尝试自动录音
        scheduleAutoRecord(m);
      }
    }
  };

  const startSession = async (itemsOverride?: WordItem[]) => {
    const items = itemsOverride ?? stateItems;
    if (items && items.length > 0) {
      setBusy(true);
      setError("");
      try {
        const topic = items[0]?.group || "速记词汇";
        const r = await api.tutorStart(topic, items);
        setBubbles([]);
        setPhase("chat");
        await applyActions(r.actions, r.state);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
      return;
    }
    if (group.length === 0) {
      setError("请先选择一个分组");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const { items } = await api.words(group[0]);
      if (items.length === 0) {
        setError("该分组没有词条");
        return;
      }
      const r = await api.tutorStart(group[0], items);
      setBubbles([]);
      setPhase("chat");
      await applyActions(r.actions, r.state);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handlePronunciation = async () => {
    if (autoRecordTimer.current) clearTimeout(autoRecordTimer.current);
    const rec = await stop();
    if (!rec.b64) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.tutorPronunciation(rec.b64, rec.format);
      await applyActions(
        r.actions, r.state,
        { role: "ai", text: r.feedback ?? "", score: r.score },
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleAnswerAudio = async () => {
    if (autoRecordTimer.current) clearTimeout(autoRecordTimer.current);
    const rec = await stop();
    if (!rec.b64) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.tutorAnswer(rec.b64, rec.format);
      await applyActions(r.actions, r.state, { role: "user", text: r.recognized ?? "" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const sendText = async () => {
    if (autoRecordTimer.current) clearTimeout(autoRecordTimer.current);
    const t = text.trim();
    if (!t) return;
    setText("");
    setBusy(true);
    setError("");
    try {
      const r = await api.tutorText(t);
      await applyActions(r.actions, r.state, { role: "user", text: t });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const chooseOption = async (chosen: string) => {
    if (autoRecordTimer.current) clearTimeout(autoRecordTimer.current);
    setBusy(true);
    setError("");
    try {
      const r = await api.tutorChoice(chosen, correctOption);
      await applyActions(r.actions, r.state, { role: "user", text: `选择：${chosen}` });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const endSession = async () => {
    if (autoRecordTimer.current) clearTimeout(autoRecordTimer.current);
    stopAudio();
    setBusy(true);
    try {
      await api.tutorStop();
    } catch {
      /* 停止失败也继续看总结 */
    }
    try {
      const s = await api.tutorSummary();
      setSummary(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      setPhase("summary");
    }
  };

  if (phase === "setup") {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="AI 家教" />
        <ErrorText text={error} />
        <p className="text-ui text-ink-soft">
          选一个分组，AI 老师会带你逐词学习：跟读 → 释义 → 造句 → 微对话。
        </p>
        <div className="flex flex-col gap-2">
          <p className="text-ui font-bold">选择分组（单选）</p>
          <GroupPicker
            selected={group}
            onChange={(g) => setGroup(g.slice(-1))}
          />
        </div>
        <button className={btnPrimary} disabled={busy} onClick={() => startSession()}>
          {busy ? "AI 老师准备中…" : "开始上课"}
        </button>
      </div>
    );
  }

  if (phase === "summary") {
    return (
      <div className="flex flex-col gap-4 py-6">
        <h1 className="text-section font-bold text-center">下课啦</h1>
        {summary ? (
          <>
            <div className="flex items-center justify-center gap-6">
              <div className="text-center">
                <p className="text-score font-extrabold text-mango-dk tabular-nums animate-pop">
                  {summary.mastered}
                </p>
                <p className="text-body text-ink-soft">掌握词数</p>
              </div>
              <div className="text-center">
                <p className="text-score font-extrabold text-ink-soft tabular-nums">
                  {summary.total_words}
                </p>
                <p className="text-body text-ink-soft">总词数</p>
              </div>
            </div>
            {summary.weak_words.length > 0 && (
              <div className="bg-clay-soft border border-clay rounded-xl p-4">
                <p className="text-ui font-bold text-clay">还要多练的词</p>
                <p className="text-body text-clay">{summary.weak_words.join(" · ")}</p>
              </div>
            )}
          </>
        ) : (
          <Spinner label="生成总结…" />
        )}
        <div className="flex gap-2 justify-center">
          <button className={btnSecondary} onClick={() => setPhase("setup")}>
            再上一课
          </button>
        </div>
      </div>
    );
  }

  // chat
  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="AI 家教" onBack={endSession} />
      {state && (
        <div className="bg-desk border border-desk-line rounded-xl px-4 py-3">
          <ProgressBar current={state.word_index + 1} total={state.total_words} />
          <div className="flex items-baseline justify-between mt-1.5">
            <p className="text-title font-bold">
              {state.word}
              <span className="text-body text-ink-soft font-normal ml-2">
                {state.translation}
              </span>
            </p>
            <span className="text-body text-ink-soft shrink-0">
              {state.in_retry ? "复习中" : state.topic}
            </span>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2 min-h-[30vh]">
        {bubbles.map((b, i) => (
          <div
            key={i}
            className={`max-w-[85%] rounded-xl px-4 py-2.5 ${
              b.role === "ai"
                ? "self-start bg-desk border border-desk-line"
                : "self-end bg-mango/90 text-ink"
            }`}
          >
            {b.score !== undefined && (
              <p className="text-body font-bold tabular-nums mb-0.5">
                <span
                  className={
                    b.score >= 80
                      ? "text-leaf"
                      : b.score >= 60
                        ? "text-mango-dk"
                        : "text-clay"
                  }
                >
                  {b.score} 分
                </span>
              </p>
            )}
            <p className="text-ui font-semibold break-words whitespace-pre-wrap">
              {b.text}
            </p>
            {b.role === "ai" && b.text && (
              <button
                type="button"
                onClick={() => speak(b.text).catch(() => {})}
                aria-label="朗读这句话"
                className="mt-1 p-1 rounded text-ink-soft hover:text-ink"
              >
                <SpeakerIcon className="w-4 h-4" />
              </button>
            )}
          </div>
        ))}
        {lastAction?.action === "session_end" && (
          <button className={`${btnPrimary} self-center mt-2`} onClick={endSession}>
            查看总结
          </button>
        )}
        <div ref={bottomRef} />
      </div>

      {mode === "choice" && (
        <div className="grid grid-cols-1 gap-2">
          {options.map((opt, i) => (
            <button
              key={i}
              type="button"
              disabled={busy}
              onClick={() => chooseOption(opt)}
              className="bg-card border border-desk-line rounded-xl px-4 py-3 text-left text-ui font-semibold hover:border-mango transition-colors disabled:opacity-40"
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      {mode === "gop" && (
        <RecordButton
          recording={recording}
          disabled={busy}
          onStart={start}
          onStop={handlePronunciation}
          hint={busy ? "评分中…" : recording ? "录音中…点击停止" : "自动录音中…"}
        />
      )}

      {mode === "asr" && (
        <>
          <RecordButton
            recording={recording}
            disabled={busy}
            onStart={start}
            onStop={handleAnswerAudio}
            hint={busy ? "思考中…" : recording ? "录音中…点击停止" : "自动录音中…"}
          />
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              sendText();
            }}
          >
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="或者打字回答"
              className={inputCls}
            />
            <button type="submit" className={btnSecondary} disabled={busy || !text.trim()}>
              发送
            </button>
          </form>
        </>
      )}

      {mode === null && lastAction?.action !== "session_end" && !busy && (
        <p className="text-body text-ink-soft text-center py-2">AI 老师正在想…</p>
      )}
      <ErrorText text={error} />
      <button
        className={`${btnSecondary} self-center text-body`}
        onClick={endSession}
        disabled={busy}
      >
        结束课程
      </button>
    </div>
  );
}
