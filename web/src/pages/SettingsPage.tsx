import { useEffect, useState } from "react";
import { api } from "../lib/api";
import GroupPicker from "../components/GroupPicker";
import {
  PageHeader, Spinner, ErrorText, btnPrimary, inputCls,
} from "../components/ui";

const TTS_OPTIONS = [
  "Auto",
  "Edge (Online - Fast)",
  "Kokoro (Local Neural - Best Quality)",
  "Piper (Local - Fast)",
  "System (Offline)",
];
const PROVIDER_OPTIONS = [
  "Custom (Local API)",
  "OpenAI (Cloud)",
  "Ollama (Local)",
];
const ASSESSOR_OPTIONS = ["gop", "omni", "azure"];
const GOP_MODE_OPTIONS = ["local", "remote"];

/** 设置 — 常用配置的表单化编辑（保存时合并进完整 config）。 */
export default function SettingsPage() {
  const [cfg, setCfg] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.config().then((c) => setCfg(c)).catch((e) => setError(e.message));
  }, []);

  const set = (key: string, value: unknown) => {
    setCfg((c) => (c ? { ...c, [key]: value } : c));
    setSaved(false);
  };

  const save = async () => {
    if (!cfg) return;
    setBusy(true);
    setError("");
    try {
      await api.saveConfig(cfg);
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!cfg) return <Spinner label="加载设置…" />;

  const activeGroups = (cfg["active_groups"] as string[]) ?? [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="设置" />
      <ErrorText text={error} />
      {saved && <p className="text-ui text-leaf font-bold">已保存</p>}

      <div className="flex flex-col gap-2">
        <label htmlFor="set-name" className="text-ui font-bold">
          学生名字（AI 老师会这样称呼）
        </label>
        <input
          id="set-name"
          value={String(cfg["student_name"] ?? "")}
          onChange={(e) => set("student_name", e.target.value)}
          className={inputCls}
        />
      </div>

      <div className="flex items-center gap-3">
        <label htmlFor="set-count" className="text-ui font-bold">
          每轮练习词数
        </label>
        <input
          id="set-count"
          type="number"
          min={1}
          max={50}
          value={Number(cfg["practice_count"] ?? 20)}
          onChange={(e) => set("practice_count", Math.max(1, Number(e.target.value) || 20))}
          className={inputCls + " w-24"}
        />
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-ui font-bold">练习分组（跟读练习从这里选词）</p>
        <GroupPicker
          selected={activeGroups}
          onChange={(g) => set("active_groups", g)}
        />
        {activeGroups.length === 0 && (
          <p className="text-body text-ink-soft">未选择时练习全部词条</p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="set-tts" className="text-ui font-bold">
          语音合成
        </label>
        <select
          id="set-tts"
          value={String(cfg["tts_engine"] ?? "Auto")}
          onChange={(e) => set("tts_engine", e.target.value)}
          className={inputCls}
        >
          {TTS_OPTIONS.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
        <p className="text-body text-ink-soft">
          Web 版朗读当前使用在线 Edge 语音，与桌面版设置无关
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="set-provider" className="text-ui font-bold">
          AI 提供商（出题 / 家教 / 情景）
        </label>
        <select
          id="set-provider"
          value={String(cfg["ai_provider"] ?? "Custom (Local API)")}
          onChange={(e) => set("ai_provider", e.target.value)}
          className={inputCls}
        >
          {PROVIDER_OPTIONS.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="set-assessor" className="text-ui font-bold">
          发音评分引擎
        </label>
        <select
          id="set-assessor"
          value={String(cfg["assessor_engine"] ?? "gop")}
          onChange={(e) => set("assessor_engine", e.target.value)}
          className={inputCls}
        >
          {ASSESSOR_OPTIONS.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="set-gop" className="text-ui font-bold">
          GOP 模式
        </label>
        <select
          id="set-gop"
          value={String(cfg["gop_mode"] ?? "local")}
          onChange={(e) => set("gop_mode", e.target.value)}
          className={inputCls}
        >
          {GOP_MODE_OPTIONS.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      </div>

      <button className={btnPrimary} disabled={busy} onClick={save}>
        {busy ? "保存中…" : "保存设置"}
      </button>
    </div>
  );
}
