/** 学习记录页 — 统计汇总 + 可续学的活跃记录 + 历史记录列表（可删除）。
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type StudyRecord, type StudyStats } from "../lib/api";
import { PageHeader, Spinner, ErrorText, btnSecondary } from "../components/ui";
import { StudyLogIcon, ResumeIcon, TrashIcon } from "../components/icons";

/** 模块 key → 路由 + 中文标签 */
const MODULE_ROUTE: Record<string, { route: string; label: string }> = {
  practice: { route: "/practice", label: "跟读练习" },
  quiz: { route: "/quiz", label: "中英互译" },
  oral: { route: "/oral-test", label: "口语测试" },
  tutor: { route: "/tutor", label: "AI 家教" },
  readalong: { route: "/readalong", label: "跟读教练" },
  scenario: { route: "/scenario", label: "情景会话" },
  memorize: { route: "/memorize/study", label: "分类速记" },
  mistakes: { route: "/mistakes", label: "错题本" },
};

/** 格式化秒数为可读时长 */
function fmtDuration(sec: number): string {
  if (sec < 60) return `${sec}秒`;
  if (sec < 3600) return `${Math.floor(sec / 60)}分${sec % 60 ? sec % 60 + "秒" : ""}`;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h}小时${m ? m + "分" : ""}`;
}

/** 日期分组 key */
function dateKey(iso: string): string {
  return iso.slice(0, 10);
}

export default function StudyLogPage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<StudyStats | null>(null);
  const [records, setRecords] = useState<StudyRecord[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const loadData = async () => {
    setBusy(true);
    setError("");
    try {
      const [s, r] = await Promise.all([
        api.studyLogStats(),
        api.studyLogRecords({ limit: 200 }),
      ]);
      setStats(s);
      setRecords(r.records);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { loadData(); }, []);

  const handleDelete = async (id: string) => {
    try {
      await api.studyLogDelete(id);
      setRecords((prev) => prev.filter((r) => r.id !== id));
      setConfirmDelete(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const handleResume = (rec: StudyRecord) => {
    const info = MODULE_ROUTE[rec.module];
    if (!info) return;
    navigate(info.route, {
      state: {
        resumeRecordId: rec.id,
        resumeSnapshot: rec.snapshot,
      },
    });
  };

  // 活跃记录（可续学）
  const activeRecords = records.filter((r) => r.status === "active" && r.snapshot);
  // 已完成/放弃的记录
  const completedRecords = records.filter((r) => r.status !== "active" || !r.snapshot);

  // 按日期分组
  const grouped: { date: string; items: StudyRecord[] }[] = [];
  for (const rec of completedRecords) {
    const dk = dateKey(rec.started_at);
    let group = grouped.find((g) => g.date === dk);
    if (!group) {
      group = { date: dk, items: [] };
      grouped.push(group);
    }
    group.items.push(rec);
  }

  if (busy) return <Spinner label="加载学习记录…" />;
  if (error && !stats) return <ErrorText text={error} />;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="学习记录" />

      {/* ── 统计卡片 ── */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="今日学习" value={fmtDuration(stats.today_sec)} />
          <StatCard label="本周学习" value={fmtDuration(stats.week_sec)} />
          <StatCard label="连续打卡" value={`${stats.streak_days}天`} />
          <StatCard label="累计次数" value={`${stats.total_count}次`} />
        </div>
      )}

      {/* ── 模块时长分布 ── */}
      {stats && Object.keys(stats.module_breakdown).length > 0 && (
        <div className="bg-desk border border-desk-line rounded-xl p-4 flex flex-col gap-2">
          <p className="text-ui font-bold">模块时长分布</p>
          {Object.entries(stats.module_breakdown)
            .sort((a, b) => b[1] - a[1])
            .map(([mod, sec]) => {
              const info = MODULE_ROUTE[mod];
              const maxSec = Math.max(...Object.values(stats.module_breakdown));
              const pct = maxSec > 0 ? (sec / maxSec) * 100 : 0;
              return (
                <div key={mod} className="flex items-center gap-2">
                  <span className="text-body w-16 shrink-0 truncate">{info?.label ?? mod}</span>
                  <div className="flex-1 h-4 bg-card rounded-full overflow-hidden">
                    <div
                      className="h-full bg-mango rounded-full transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-body text-ink-soft w-16 text-right tabular-nums shrink-0">
                    {fmtDuration(sec)}
                  </span>
                </div>
              );
            })}
        </div>
      )}

      {/* ── 活跃会话（可续学）── */}
      {activeRecords.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-ui font-bold">未完成的学习</p>
          {activeRecords.map((rec) => (
            <div
              key={rec.id}
              className="bg-mango/10 border border-mango rounded-xl px-4 py-3 flex items-center gap-3"
            >
              <div className="flex-1 min-w-0">
                <p className="text-ui font-bold">{rec.module_label}</p>
                <p className="text-body text-ink-soft">
                  {rec.content_summary || "进行中"}
                  {rec.duration_sec > 0 && ` · 已学${fmtDuration(rec.duration_sec)}`}
                </p>
              </div>
              <button
                className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-mango text-ink text-ui font-bold hover:bg-mango-dk transition-colors"
                onClick={() => handleResume(rec)}
              >
                <ResumeIcon className="w-4 h-4" />
                继续
              </button>
              <button
                className="shrink-0 p-1.5 rounded-lg text-ink-soft hover:text-clay hover:bg-clay-soft transition-colors"
                onClick={() => setConfirmDelete(rec.id)}
                aria-label="删除"
              >
                <TrashIcon className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* ── 历史记录 ── */}
      <div className="flex flex-col gap-2">
        <p className="text-ui font-bold">历史记录</p>
        {grouped.length === 0 && (
          <p className="text-body text-ink-soft">还没有学习记录，开始你的第一次学习吧！</p>
        )}
        {grouped.map((g) => (
          <div key={g.date} className="flex flex-col gap-1.5">
            <p className="text-body text-ink-soft font-bold mt-1">{g.date}</p>
            {g.items.map((rec) => (
              <div
                key={rec.id}
                className="bg-desk border border-desk-line rounded-xl px-4 py-3 flex items-center gap-3"
              >
                <StudyLogIcon className="w-4 h-4 text-ink-soft shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-ui font-bold truncate">{rec.module_label}</p>
                  <p className="text-body text-ink-soft truncate">
                    {rec.content_summary || "—"}
                    {rec.duration_sec > 0 && ` · ${fmtDuration(rec.duration_sec)}`}
                  </p>
                </div>
                <span className="text-body text-ink-soft/60 tabular-nums shrink-0">
                  {rec.started_at.slice(11, 16)}
                </span>
                <button
                  className="shrink-0 p-1.5 rounded-lg text-ink-soft/40 hover:text-clay hover:bg-clay-soft transition-colors"
                  onClick={() => setConfirmDelete(rec.id)}
                  aria-label="删除"
                >
                  <TrashIcon className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* ── 删除确认弹层 ── */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30">
          <div className="bg-card border border-desk-line rounded-xl p-5 mx-4 max-w-sm w-full flex flex-col gap-3 shadow-lg">
            <p className="text-title font-bold">删除这条记录？</p>
            <p className="text-body text-ink-soft">删除后无法恢复，但不会影响已有的学习数据。</p>
            <div className="flex gap-2 justify-end">
              <button className={btnSecondary} onClick={() => setConfirmDelete(null)}>
                取消
              </button>
              <button
                className="px-4 py-2 rounded-lg bg-clay text-white text-ui font-bold hover:bg-clay/80 transition-colors"
                onClick={() => handleDelete(confirmDelete)}
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}

      <ErrorText text={error} />
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-desk border border-desk-line rounded-xl p-3 flex flex-col items-center gap-0.5">
      <p className="text-title font-extrabold text-mango-dk tabular-nums">{value}</p>
      <p className="text-body text-ink-soft">{label}</p>
    </div>
  );
}
