import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type MemorizeDay, type MemorizeEntry } from "../lib/api";
import {
  PageHeader, Spinner, ErrorText,
  btnPrimary, btnSecondary,
} from "../components/ui";

/** 分类速记 — 28 天计划：开始 / 复习 / 拿去跟读练习 / 情景会话 / AI 家教。 */
export default function MemorizePage() {
  const navigate = useNavigate();
  const [days, setDays] = useState<MemorizeDay[] | null>(null);
  const [due, setDue] = useState<{ day: number; stage: number; due_date: string }[]>([]);
  const [sel, setSel] = useState<MemorizeDay | null>(null);
  const [selectedDays, setSelectedDays] = useState<number[]>([]);
  const [entries, setEntries] = useState<MemorizeEntry[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = () => {
    api.memorizeDays().then((r) => setDays(r.days)).catch((e) => setError(e.message));
    api.memorizeDue().then((r) => setDue(r.due)).catch(() => {});
  };

  useEffect(refresh, []);

  const toggleDay = (day: number) => {
    setSelectedDays((prev) =>
      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day],
    );
  };

  const openDay = async (d: MemorizeDay) => {
    setSel(d);
    setEntries(null);
    setError("");
    try {
      const r = await api.memorizeDay(d.day);
      setEntries(r.entries);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const start = async (day: number) => {
    setBusy(true);
    try {
      await api.memorizeStart(day);
      refresh();
      setSel((s) => (s ? { ...s, started: true } : s));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const review = async (day: number) => {
    setBusy(true);
    try {
      await api.memorizeReview(day);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const practice = () => {
    if (!sel || !entries) return;
    const items = entries.map((e) => ({
      text: e.text,
      translation: e.translation,
      group: `速记Day${sel.day}`,
      pos: e.pos,
    }));
    navigate("/practice", { state: { items } });
  };

  /** 收集选中 Day 的词条，跳转到情景会话或 AI 家教。 */
  const goModule = async (path: string) => {
    const dayList = sel ? [sel.day] : selectedDays;
    if (dayList.length === 0) {
      setError("请先选择至少一天");
      return;
    }
    setBusy(true);
    setError("");
    try {
      // 拉取所有选中 Day 的词条
      const allEntries: MemorizeEntry[] = [];
      for (const d of dayList) {
        const r = await api.memorizeDay(d);
        allEntries.push(...r.entries);
      }
      if (allEntries.length === 0) {
        setError("选中的天没有词条");
        return;
      }
      const items = allEntries.map((e) => ({
        text: e.text,
        translation: e.translation,
        group: `速记Day${dayList.join(",")}`,
        pos: e.pos,
      }));
      navigate(path, { state: { items } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (sel) {
    const prog = sel.progress;
    const stage = prog?.stage ?? 0;
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title={sel.title} onBack={() => setSel(null)} />
        <ErrorText text={error} />
        {prog ? (
          <div className="bg-desk border border-desk-line rounded-xl px-4 py-3 flex items-center justify-between">
            <p className="text-ui font-bold">
              复习进度 {stage}/{prog.total_stages}
            </p>
            <p className="text-body text-ink-soft">
              {stage >= prog.total_stages
                ? "已完成"
                : prog.next_due
                  ? `下次复习 ${prog.next_due}`
                  : ""}
            </p>
          </div>
        ) : (
          <p className="text-body text-ink-soft">还没开始这一天的学习</p>
        )}

        {!entries && <Spinner label="加载词条…" />}
        <div className="flex flex-col gap-2">
          {entries?.map((e, i) => (
            <div
              key={i}
              className="bg-card border border-desk-line rounded-lg px-3 py-2 flex items-baseline gap-2"
            >
              <span className="text-ui font-bold">{e.text}</span>
              {e.pos && <span className="text-body text-ink-soft">{e.pos}</span>}
              <span className="text-body text-ink-soft ml-auto">{e.translation}</span>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
          <button className={btnSecondary} disabled={busy} onClick={practice}>
            跟读这些词
          </button>
          <button className={btnSecondary} disabled={busy} onClick={() => goModule("/scenario")}>
            情景会话
          </button>
          <button className={btnSecondary} disabled={busy} onClick={() => goModule("/tutor")}>
            AI 家教
          </button>
          {!sel.started ? (
            <button className={btnPrimary} disabled={busy} onClick={() => start(sel.day)}>
              开始学习
            </button>
          ) : stage < (prog?.total_stages ?? 5) ? (
            <button className={btnPrimary} disabled={busy} onClick={() => review(sel.day)}>
              完成今日复习
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="分类速记" />
      <ErrorText text={error} />

      {due.length > 0 && (
        <div className="bg-mango/20 border border-mango rounded-xl p-4">
          <p className="text-ui font-bold">今天要复习</p>
          <p className="text-body text-ink-soft">
            {due.map((d) => `Day ${d.day}`).join(" · ")}
          </p>
        </div>
      )}

      {selectedDays.length > 0 && (
        <div className="bg-desk border border-desk-line rounded-xl px-4 py-3 flex items-center justify-between">
          <p className="text-ui font-bold">
            已选 {selectedDays.length} 天
          </p>
          <div className="flex gap-2">
            <button
              className={btnSecondary}
              disabled={busy}
              onClick={() => goModule("/scenario")}
            >
              情景会话
            </button>
            <button
              className={btnPrimary}
              disabled={busy}
              onClick={() => goModule("/tutor")}
            >
              AI 家教
            </button>
          </div>
        </div>
      )}

      {!days && <Spinner label="加载计划…" />}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
        {days?.map((d) => {
          const picked = selectedDays.includes(d.day);
          return (
            <button
              key={d.day}
              type="button"
              onClick={() => toggleDay(d.day)}
              onDoubleClick={() => openDay(d)}
              className={`bg-desk rounded-xl p-3 text-left border transition-colors hover:bg-[#DDD7C6] ${
                picked
                  ? "border-l-4 border-mango bg-mango/10"
                  : d.started
                    ? "border-l-4 border-mango"
                    : "border-desk-line"
              }`}
            >
              <p className="text-ui font-bold">
                {picked && "✓ "}Day {d.day}
              </p>
              <p className="text-body text-ink-soft truncate">{d.title}</p>
              <p className="text-body text-ink-soft">
                {d.count} 词{d.started ? ` · 复习 ${d.progress?.stage ?? 0} 轮` : ""}
              </p>
            </button>
          );
        })}
      </div>
      <p className="text-body text-ink-soft text-center">
        单击选择 → 情景会话 / AI 家教 · 双击查看详情 / 跟读
      </p>
    </div>
  );
}
