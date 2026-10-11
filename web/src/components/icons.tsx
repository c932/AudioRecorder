// 线性图标 — 24px 网格、2px 描边，与 storybook desk 的圆润气质一致。
import type { ReactNode } from "react";

interface IconProps {
  className?: string;
}

function Svg({ className = "size-6", children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      {children}
    </svg>
  );
}

export function HomeIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M3.5 10.5 12 3.5l8.5 7" />
      <path d="M5.5 9.5V20.5h13V9.5" />
    </Svg>
  );
}

export function MicIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="9" y="2.5" width="6" height="12" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0" />
      <path d="M12 18v3.5" />
    </Svg>
  );
}

export function QuizIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 9.5h8M8 13h8M8 16.5h4" />
    </Svg>
  );
}

export function ChatIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="4" y="4" width="16" height="12" rx="3" />
      <path d="M8 16v4l4-4" />
    </Svg>
  );
}

export function MoreIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="4" y="4" width="6.5" height="6.5" rx="2" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="2" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="2" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="2" />
    </Svg>
  );
}

/** 口语测试 — 气泡 + 勾 */
export function OralTestIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="4" y="4" width="16" height="12" rx="3" />
      <path d="M8 16v4l4-4" />
      <path d="M9 10l2 2 4-4" />
    </Svg>
  );
}

/** AI 家教 — 气泡 + 星 */
export function TutorIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="4" y="4" width="16" height="12" rx="3" />
      <path d="M8 16v4l4-4" />
      <path d="M12 6.5l.8 1.7 1.9.3-1.4 1.3.3 1.9-1.6-.9-1.6.9.3-1.9L9.3 8.5l1.9-.3z" />
    </Svg>
  );
}

/** 跟读教练 — 麦克风 + 音波 */
export function ReadAlongIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="9" y="2.5" width="6" height="12" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0" />
      <path d="M12 18v3.5" />
      <path d="M17 5.5a8 8 0 0 1 0 13" />
    </Svg>
  );
}

/** 分类速记 — 堆叠卡片 */
export function MemorizeIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="5" y="5" width="14" height="14" rx="2" />
      <path d="M8 5V3h12v14" />
      <path d="M8 10h6M8 13.5h4" />
    </Svg>
  );
}

/** 错题本 — 叉号圆圈 */
export function MistakesIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </Svg>
  );
}

/** 情景会话 — 双气泡 */
export function ScenarioIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="2" y="5" width="12" height="9" rx="2.5" />
      <path d="M6 14v3l3-3" />
      <rect x="10" y="10" width="12" height="9" rx="2.5" />
      <path d="M18 19v3l3-3" />
    </Svg>
  );
}

export function StopIcon({ className = "w-8 h-8" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <rect x="7" y="7" width="10" height="10" rx="2" />
    </svg>
  );
}

export function SpeakerIcon({ className = "w-5 h-5" }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M4 9.5v5h3.5L13 19V5L7.5 9.5H4z" fill="currentColor" stroke="none" />
      <path d="M16.5 8.5a5 5 0 0 1 0 7" />
      <path d="M19 6a8.5 8.5 0 0 1 0 12" />
    </Svg>
  );
}

export function BackIcon({ className = "w-5 h-5" }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M15 5l-7 7 7 7" />
    </Svg>
  );
}

export function ForwardIcon({ className = "w-5 h-5" }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M9 5l7 7-7 7" />
    </Svg>
  );
}
