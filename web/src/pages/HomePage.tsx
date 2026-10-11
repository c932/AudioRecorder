import { Link, useNavigate } from "react-router-dom";
import { MicIcon, QuizIcon, ChatIcon, MoreIcon } from "../components/icons";

/**
 * 主页一级入口 — 口语测试 / AI家教 / 跟读教练 / 分类速记 / 错题本
 * 跟读练习、中英互译、情景会话、导入词库、设置保留在二级页面。
 */
const SECTIONS = [
  {
    to: "/oral-test",
    zh: "口语测试",
    en: "Oral Test",
    icon: ChatIcon,
    desc: "看题作答 · 限时录音 · 评分反馈",
    children: null,
  },
  {
    to: "/tutor",
    zh: "AI 家教",
    en: "AI Tutor",
    icon: ChatIcon,
    desc: "自由对话 · 话题引导 · 实时纠错",
    children: null,
  },
  {
    to: "/readalong",
    zh: "跟读教练",
    en: "Read-Along Coach",
    icon: MicIcon,
    desc: "逐句跟读 · 音素级评分",
    children: null,
  },
  {
    to: "/memorize",
    zh: "分类速记",
    en: "28-Day Memorize",
    icon: MoreIcon,
    desc: "按天推进的词汇计划",
    children: null,
  },
  {
    to: "/mistakes",
    zh: "错题本",
    en: "Review Mistakes",
    icon: QuizIcon,
    desc: "发音低分词 + 翻译错词",
    children: null,
  },
  {
    to: "/more",
    zh: "更多",
    en: "More",
    icon: MoreIcon,
    desc: "跟读练习 · 互译 · 情景会话 · 导入 · 设置",
    children: [
      { to: "/practice", zh: "跟读练习" },
      { to: "/quiz", zh: "中英互译" },
      { to: "/scenario", zh: "情景会话" },
      { to: "/import", zh: "导入词库" },
      { to: "/settings", zh: "设置" },
    ],
  },
] as const;

export default function HomePage() {
  const navigate = useNavigate();
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

      <div className="grid grid-cols-2 gap-3 w-full">
        {SECTIONS.map((s) => {
          const Icon = s.icon;
          return (
            <Link
              key={s.to}
              to={s.to}
              className="bg-desk rounded-xl p-4 flex flex-col gap-1.5 border border-desk-line hover:bg-[#DDD7C6] active:bg-[#CFC8B5] transition-colors"
            >
              <div className="flex items-center gap-2">
                <Icon className="w-5 h-5 text-mango-dk shrink-0" />
                <span className="text-title font-bold">{s.zh}</span>
              </div>
              <span className="text-body text-ink-soft">{s.en}</span>
              <span className="text-[11px] text-ink-soft/70 leading-snug">{s.desc}</span>
              {s.children && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {s.children.map((c) => (
                    <button
                      key={c.to}
                      type="button"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(c.to); }}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-card border border-desk-line text-ink-soft hover:text-mango-dk transition-colors"
                    >
                      {c.zh}
                    </button>
                  ))}
                </div>
              )}
            </Link>
          );
        })}
      </div>

      <a
        href="/api/cert/root-ca"
        download="rootCA.pem"
        className="text-body text-ink-soft/60 underline decoration-dotted underline-offset-2 hover:text-ink-soft transition-colors mt-2"
      >
        安装录音证书（iPad / 手机）
      </a>
    </div>
  );
}
