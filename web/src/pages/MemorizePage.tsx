import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type MemorizeDay, type MemorizeEntry } from "../lib/api";
import {
  PageHeader, Spinner, ErrorText,
  btnPrimary, btnSecondary,
} from "../components/ui";

/** 分类速记 — 选 Day → 学习 / 复习 / 跟读 三个子模块。 */
export default function MemorizePage() {
  const navigate = useNavigate();
  const [days, setDays] = useState<MemorizeDay[] | null>(null);
  const [due, setDue] = useState<{ day: number; stage: number; due_date: string }[]>([]);
  const [sel, setSel] = useState<MemorizeDay | null>(null);
  const [entries, setEntries] = useState<MemorizeEntry[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = () => {
    api.memorizeDays().then((r) => setDays(r.days)).catch((e) => setError(e.message));
    api.memorizeDue().then((r) => setDue(r.due)).catch(() => {});
  };

  useEffect(refresh, []);

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

  const goStudy = () => {
    if (!sel || !entries) return;
    navigate("/memorize/study", { state: { day: sel.day, title: sel.title, entries } });
  };

  const goReview = () => {
    if (!sel) return;
    navigate("/memorize/review", { state: { day: sel.day, title: sel.title } });
  };

  const goPractice = () => {
    if (!sel || !entries) return;
    const items = entries.map((e) => ({
      text: e.text,
      translation: e.translation,
      group: `速记Day${sel.day}`,
      pos: e.pos,
    }));
    navigate("/practice", { state: { items } });
  };

  // ── Day 详情：三个子模块入口 ──
  if (sel) {
    const prog = sel.progress;
    const stage = prog?.stage ?? 0;
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title={sel.title} onBack={() => setSel(null)} />
        <ErrorText text={error} />

        {/* 进度条 */}
        {prog && (
          <div className="bg-desk border border-desk-line rounded-xl px-4 py-3 flex items-center justify-between">
            <p className="text-ui font-bold">复习进度 {stage}/{prog.total_stages}</p>
            <p className="text-body text-ink-soft">
              {stage >= prog.total_stages ? "已完成" : prog.next_due ? `下次复习 ${prog.next_due}` : ""}
            </p>
          </div>
        )}

        {/* 词条预览 */}
        {!entries && <Spinner label="加载词条…" />}
        {entries && (
          <p className="text-body text-ink-soft">{entries.length} 个词条</p>
        )}

        {/* 三子模块入口 */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <button
            className="bg-desk rounded-xl p-4 flex flex-col gap-1 border border-desk-line hover:bg-[#DDD7C6] active:bg-[#CFC8B5] transition-colors text-left"
            onClick={goStudy}
          >
            <span className="text-title font-bold">📖 学习</span>
            <span className="text-body text-ink-soft">闪卡翻页 · 英中对照</span>
          </button>
          <button
            className="bg-desk rounded-xl p-4 flex flex-col gap-1 border border-desk-line hover:bg-[#DDD7C6] active:bg-[#CFC8B5] transition-colors text-left"
            onClick={goReview}
          >
            <span className="text-title font-bold">✍️ 复习</span>
            <span className="text-body text-ink-soft">英翻中 / 中翻英四选一</span>
          </button>
          <button
            className="bg-desk rounded-xl p-4 flex flex-col gap-1 border border-desk-line hover:bg-[#DDD7C6] active:bg-[#CFC8B5] transition-colors text-left"
            onClick={goPractice}
          >
            <span className="text-title font-bold">🎤 跟读</span>
            <span className="text-body text-ink-soft">录音评分练习</span>
          </button>
        </div>

        {/* 艾宾浩斯进度按钮 */}
        <div className="flex flex-wrap gap-2 mt-2">
          {!sel.started ? (
            <button className={btnPrimary} disabled={busy} onClick={() => start(sel.day)}>
              开始学习
            </button>
          ) : stage < (prog?.total_stages ?? 5) ? (
            <button className={btnSecondary} disabled={busy} onClick={() => review(sel.day)}>
              完成今日复习
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  // ── Day 列表 ──
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="分类速记" />
      <ErrorText text={error} />

      {due.length > 0 && (
        <div className="bg-mango/20 border border-mango rounded-xl p-4">
          <p className="text-ui font-bold">今天要复习</p>
          <p className="text-body text-ink-soft">{due.map((d) => `Day ${d.day}`).join(" · ")}</p>
        </div>
      )}

      {!days && <Spinner label="加载计划…" />}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
        {days?.map((d) => (
          <button
            key={d.day}
            type="button"
            onClick={() => openDay(d)}
            className={`bg-desk rounded-xl p-3 text-left border transition-colors hover:bg-[#DDD7C6] ${
              d.started ? "border-l-4 border-mango" : "border-desk-line"
            }`}
          >
            <p className="text-ui font-bold">Day {d.day}</p>
            <p className="text-body text-ink-soft truncate">{d.title}</p>
            <p className="text-body text-ink-soft">
              {d.count} 词{d.started ? ` · 复习 ${d.progress?.stage ?? 0} 轮` : ""}
            </p>
          </button>
        ))}
      </div>
      <p className="text-body text-ink-soft text-center">点击选择一天开始学习</p>
    </div>
  );
}
