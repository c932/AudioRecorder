import { Link } from "react-router-dom";
import { PageHeader } from "../components/ui";

const MODULES = [
  { to: "/oral-test", zh: "口语测试", en: "Oral Reading Test", desc: "整句朗读 · 逐句打分" },
  { to: "/scenario", zh: "情景会话", en: "Scenario Chat", desc: "角色扮演 · 情景对话" },
  { to: "/tutor", zh: "AI 家教", en: "AI Tutor", desc: "一对一带学新词" },
];

/** 口语枢纽 — 三种口语训练模式的入口。 */
export default function OralHubPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="口语训练" />
      <div className="grid gap-3">
        {MODULES.map((m) => (
          <Link
            key={m.to}
            to={m.to}
            className="bg-desk rounded-xl p-5 border border-desk-line hover:bg-[#DDD7C6] active:bg-[#CFC8B5] transition-colors"
          >
            <p className="text-title font-bold">{m.zh}</p>
            <p className="text-body text-ink-soft mt-0.5">
              {m.en} · {m.desc}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
