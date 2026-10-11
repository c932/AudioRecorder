import { Link } from "react-router-dom";
import {
  MicIcon,
  QuizIcon,
  OralTestIcon,
  TutorIcon,
  ReadAlongIcon,
  MemorizeIcon,
  MistakesIcon,
} from "../components/icons";

const SECTIONS = [
  {
    to: "/practice",
    zh: "跟读练习",
    en: "Read & Score",
    icon: MicIcon,
    desc: "听标准音 · 录音 · 音素级评分",
  },
  {
    to: "/quiz",
    zh: "中英互译",
    en: "Translation Quiz",
    icon: QuizIcon,
    desc: "看词选义 · 看义选词",
  },
  {
    to: "/oral-test",
    zh: "口语测试",
    en: "Oral Test",
    icon: OralTestIcon,
    desc: "看题作答 · 限时录音 · 评分反馈",
  },
  {
    to: "/tutor",
    zh: "AI 家教",
    en: "AI Tutor",
    icon: TutorIcon,
    desc: "自由对话 · 话题引导 · 实时纠错",
  },
  {
    to: "/readalong",
    zh: "跟读教练",
    en: "Read-Along Coach",
    icon: ReadAlongIcon,
    desc: "逐句跟读 · 音素级评分",
  },
  {
    to: "/memorize",
    zh: "分类速记",
    en: "28-Day Memorize",
    icon: MemorizeIcon,
    desc: "按天推进的词汇计划",
  },
  {
    to: "/mistakes",
    zh: "错题本",
    en: "Review Mistakes",
    icon: MistakesIcon,
    desc: "发音低分词 + 翻译错词",
  },
] as const;

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
