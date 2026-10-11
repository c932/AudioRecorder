import { Link } from "react-router-dom";

const MODULES = [
  { to: "/practice", zh: "跟读练习", en: "Read & Score", desc: "听标准音 · 录音 · 音素级评分" },
  { to: "/quiz", zh: "中英互译", en: "Translation Quiz", desc: "看词选义 · 看义选词" },
  { to: "/scenario", zh: "情景会话", en: "Scenario Dialogue", desc: "LLM 生成的 A/B 角色对话" },
  { to: "/import", zh: "导入词库", en: "Import Words", desc: "粘贴文本批量建词" },
  { to: "/settings", zh: "设置", en: "Settings", desc: "练习偏好与引擎选择" },
];

/** 「更多」标签页 — 底部导航放不下的模块入口。 */
export default function MorePage() {
  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-section font-bold">更多</h1>
      <div className="grid gap-3">
        {MODULES.map((m) => (
          <Link
            key={m.to}
            to={m.to}
            className="bg-desk rounded-xl p-4 border border-desk-line hover:bg-[#DDD7C6] active:bg-[#CFC8B5] transition-colors"
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
