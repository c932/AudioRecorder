import { NavLink, Outlet } from "react-router-dom";
import { HomeIcon, MicIcon, QuizIcon, ChatIcon, MoreIcon } from "./icons";

const TABS = [
  { to: "/", label: "首页", icon: HomeIcon, end: true },
  { to: "/practice", label: "练习", icon: MicIcon, end: false },
  { to: "/quiz", label: "测验", icon: QuizIcon, end: false },
  { to: "/oral", label: "口语", icon: ChatIcon, end: false },
  { to: "/more", label: "更多", icon: MoreIcon, end: false },
];

/** 移动端底部标签栏（拇指可达）+ 桌面顶部导航。 */
export default function Layout() {
  return (
    <div className="min-h-dvh flex flex-col">
      <header className="hidden md:flex items-center gap-3 px-6 h-14 border-b border-desk-line bg-card sticky top-0 z-10">
        <img src="/mascot.png" alt="" className="h-9 w-9 object-contain" />
        <span className="font-extrabold text-title mr-6">英语教练</span>
        <nav className="flex items-center gap-1">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-lg text-ui font-bold transition-colors ${
                  isActive ? "bg-mango text-ink" : "text-ink-soft hover:bg-desk hover:text-ink"
                }`
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="flex-1 w-full max-w-4xl mx-auto px-4 py-5 pb-[calc(80px+env(safe-area-inset-bottom))] md:pb-10">
        <Outlet />
      </main>

      <nav className="md:hidden fixed bottom-0 inset-x-0 z-10 bg-card border-t border-desk-line flex justify-around pt-1 pb-[env(safe-area-inset-bottom)]">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              `flex flex-col items-center gap-0.5 px-3 py-1.5 min-w-16 rounded-lg text-[11px] font-bold transition-colors ${
                isActive ? "text-mango-dk" : "text-ink-soft"
              }`
            }
          >
            <t.icon className="w-6 h-6" />
            <span>{t.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
