import { Link } from "react-router-dom";

const MODULES = [
  { to: "/memorize", zh: "分类速记", en: "28-Day Memorize", desc: "按天推进的词汇计划" },
  { to: "/mistakes", zh: "错题本", en: "Review Mistakes", desc: "发音低分词 + 翻译错词" },
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
