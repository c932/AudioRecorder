import { Link } from "react-router-dom";

const MODULES = [
  { to: "/practice", zh: "跟读练习", en: "Read & Score", active: true },
  { to: "/quiz", zh: "中英互译", en: "Translation Quiz", active: false },
  { to: "/scenario", zh: "情景会话", en: "Scenario Chat", active: false },
  { to: "/tutor", zh: "AI 家教", en: "AI Tutor", active: false },
  { to: "/memorize", zh: "分类速记", en: "28-Day Memorize", active: false },
  { to: "/mistakes", zh: "复习错误", en: "Review Mistakes", active: false },
  { to: "/import", zh: "导入词库", en: "Import Words", active: false },
  { to: "/settings", zh: "设置", en: "Settings", active: false },
];

export default function HomePage() {
  return (
    <div className="flex flex-col items-center gap-6 pt-2">
      <img
        src="/mascot.png"
        alt="鹦鹉教练"
        className="w-24 h-24 object-contain animate-sway"
      />
      <div className="text-center">
        <h1 className="text-header font-extrabold">英语发音教练</h1>
        <p className="text-ui text-ink-soft mt-1">今天练点什么？</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 w-full">
        {MODULES.map((m) => (
          <Link
            key={m.to}
            to={m.to}
            className={`bg-desk rounded-xl p-4 flex flex-col gap-1 transition-colors hover:bg-[#DDD7C6] active:bg-[#CFC8B5] ${
              m.active ? "border-l-4 border-mango" : "border border-desk-line"
            }`}
          >
            <span className="text-title font-bold">{m.zh}</span>
            <span className="text-body text-ink-soft">{m.en}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
