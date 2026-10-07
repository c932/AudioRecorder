// 分组多选器 — 词库分组芯片 + 速记28天模块（测验/口语/情景/家教/练习共用）。
import { useEffect, useState } from "react";
import { api, type GroupInfo } from "../lib/api";

interface Props {
  selected: string[];
  onChange: (groups: string[]) => void;
}

export default function GroupPicker({ selected, onChange }: Props) {
  const [groups, setGroups] = useState<GroupInfo[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.groups().then((r) => r.groups),
      api.memorizeDays().then((r) =>
        r.days.map((d) => ({ name: `速记Day${d.day}`, count: d.count })),
      ),
    ])
      .then(([vocabGroups, memDays]) => setGroups([...vocabGroups, ...memDays]))
      .catch((e) => setError(e.message));
  }, []);

  const toggle = (name: string) => {
    onChange(
      selected.includes(name) ? selected.filter((g) => g !== name) : [...selected, name],
    );
  };

  if (error) return <p className="text-body text-clay font-semibold">{error}</p>;
  if (groups.length === 0) return <p className="text-body text-ink-soft">加载分组中…</p>;

  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="选择分组">
      {groups.map((g) => {
        const on = selected.includes(g.name);
        return (
          <button
            key={g.name}
            type="button"
            onClick={() => toggle(g.name)}
            aria-pressed={on}
            className={`px-3 py-1.5 rounded-lg text-body font-bold border transition-colors ${
              on
                ? "bg-mango border-mango-dk text-ink"
                : "bg-card border-desk-line text-ink-soft hover:border-mango hover:text-ink"
            }`}
          >
            {g.name}
            <span className="ml-1 opacity-60 tabular-nums">{g.count}</span>
          </button>
        );
      })}
    </div>
  );
}
