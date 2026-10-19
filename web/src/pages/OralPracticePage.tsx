import { useState } from "react";
import { useLocation } from "react-router-dom";
import OralTestPage from "./OralTestPage";
import ScenarioPage from "./ScenarioPage";

type OralMode = "reading" | "dialogue";

const TABS: { key: OralMode; zh: string; en: string; desc: string }[] = [
  { key: "reading", zh: "口语朗读", en: "Reading Test", desc: "整句朗读 · 逐句打分" },
  { key: "dialogue", zh: "情景对话", en: "Scenario Chat", desc: "角色扮演 · 逐句跟读" },
];

/** 口语练习 — 口语朗读 + 情景对话两种模式合一。 */
export default function OralPracticePage() {
  const location = useLocation();
  const state = (location.state as { mode?: OralMode; resumeSnapshot?: unknown } | null) ?? {};
  // 续学情景会话记录时自动切到对话 tab（其快照含 results 数组，朗读快照是 scores）
  const initial =
    state.mode ??
    (state.resumeSnapshot && Array.isArray((state.resumeSnapshot as { results?: unknown[] }).results)
      ? "dialogue"
      : "reading");
  const [mode, setMode] = useState<OralMode>(initial);

  const tab = TABS.find((t) => t.key === mode)!;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex rounded-xl bg-desk border border-desk-line p-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setMode(t.key)}
            className={`flex-1 rounded-lg px-3 py-2 text-ui font-bold transition-colors ${
              mode === t.key ? "bg-mango text-ink" : "text-ink-soft hover:text-ink"
            }`}
          >
            {t.zh}
          </button>
        ))}
      </div>
      <p className="text-body text-ink-soft text-center">{tab.en} · {tab.desc}</p>

      {mode === "reading" ? <OralTestPage /> : <ScenarioPage />}
    </div>
  );
}
