import { useEffect, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import GroupPicker from "../components/GroupPicker";
import {
  PageHeader, Spinner, ErrorText, btnPrimary, btnSecondary, inputCls,
} from "../components/ui";

const TTS_OPTIONS = [
  "Auto",
  "CosyVoice (GPU 本地 — 中英混合)",
  "Edge (在线 — 快速)",
];
const PROVIDER_OPTIONS = [
  "Custom (Local API)",
  "OpenAI (Cloud)",
  "Ollama (Local)",
  "MiniCPM-o (Omni 本地多模态)",
];
const ASSESSOR_OPTIONS = ["gop", "omni", "azure"];
const GOP_MODE_OPTIONS = ["local", "remote"];

interface TestResult {
  ok: boolean;
  message: string;
  models?: string[];
}

function Field({
  label, hint, htmlFor, children,
}: { label: string; hint?: string; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-ui font-bold">{label}</label>
      {children}
      {hint && <p className="text-body text-ink-soft">{hint}</p>}
    </div>
  );
}

/** 设置 — 常用配置的表单化编辑（保存时合并进完整 config）。 */
export default function SettingsPage() {
  const [cfg, setCfg] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

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

  const test = async () => {
    if (!cfg) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testConfig(cfg);
      setTestResult(r);
    } catch (e) {
      setTestResult({ ok: false, message: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };

  if (!cfg) return <Spinner label="加载设置…" />;

  const activeGroups = (cfg["active_groups"] as string[]) ?? [];
  const provider = String(cfg["ai_provider"] ?? "Custom (Local API)");
  // 桌面版可能存了历史值（如 Azure）——保底显示，避免下拉框空选
  const providerOptions = PROVIDER_OPTIONS.includes(provider)
    ? PROVIDER_OPTIONS
    : [provider, ...PROVIDER_OPTIONS];
  const isOmni = provider.includes("Omni") || provider.includes("MiniCPM");
  const isOpenAI = provider.includes("OpenAI");
  const isCustom = provider.includes("Custom");
  const isOllama = provider.includes("Ollama");
  const models = testResult?.models ?? [];

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
          Auto 优先 CosyVoice GPU，失败回退 Edge 在线
        </p>
      </div>

      {/* AI 提供商 — 按所选提供商显示配套字段，可先测连通再保存 */}
      <div className="flex flex-col gap-3 bg-card border border-desk-line rounded-xl p-4">
        <div className="flex flex-col gap-2">
          <label htmlFor="set-provider" className="text-ui font-bold">
            AI 提供商（出题 / 家教 / 情景）
          </label>
          <select
            id="set-provider"
            value={provider}
            onChange={(e) => {
              set("ai_provider", e.target.value);
              setTestResult(null);
            }}
            className={inputCls}
          >
            {providerOptions.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </div>

        {isOpenAI && (
          <>
            <Field label="API 密钥" htmlFor="set-oai-key">
              <input
                id="set-oai-key"
                type="password"
                autoComplete="off"
                value={String(cfg["openai_key"] ?? "")}
                onChange={(e) => set("openai_key", e.target.value)}
                className={inputCls}
                placeholder="sk-…"
              />
            </Field>
            <Field label="接口地址" htmlFor="set-oai-base" hint="兼容 OpenAI 接口的服务都可以填这里">
              <input
                id="set-oai-base"
                value={String(cfg["openai_base"] ?? "")}
                onChange={(e) => set("openai_base", e.target.value)}
                className={inputCls}
                placeholder="https://api.openai.com/v1"
              />
            </Field>
            <Field label="模型" htmlFor="set-oai-model">
              <input
                id="set-oai-model"
                list="llm-models"
                value={String(cfg["openai_model"] ?? "")}
                onChange={(e) => set("openai_model", e.target.value)}
                className={inputCls}
                placeholder="gpt-4o"
              />
            </Field>
          </>
        )}

        {isCustom && (
          <>
            <Field label="接口地址" htmlFor="set-custom-base" hint="llama.cpp / vLLM 等 OpenAI 兼容 API">
              <input
                id="set-custom-base"
                value={String(cfg["custom_base"] ?? "")}
                onChange={(e) => set("custom_base", e.target.value)}
                className={inputCls}
                placeholder="http://192.168.50.200:9090/v1"
              />
            </Field>
            <Field label="API 密钥" htmlFor="set-custom-key" hint="本地服务通常留空">
              <input
                id="set-custom-key"
                type="password"
                autoComplete="off"
                value={String(cfg["custom_key"] ?? "")}
                onChange={(e) => set("custom_key", e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="模型" htmlFor="set-custom-model">
              <input
                id="set-custom-model"
                list="llm-models"
                value={String(cfg["custom_model"] ?? "")}
                onChange={(e) => set("custom_model", e.target.value)}
                className={inputCls}
                placeholder="Qwen3.6-35B"
              />
            </Field>
          </>
        )}

        {isOllama && (
          <>
            <Field label="接口地址" htmlFor="set-ollama-base">
              <input
                id="set-ollama-base"
                value={String(cfg["ollama_base"] ?? "")}
                onChange={(e) => set("ollama_base", e.target.value)}
                className={inputCls}
                placeholder="http://localhost:11434/v1"
              />
            </Field>
            <Field label="模型" htmlFor="set-ollama-model">
              <input
                id="set-ollama-model"
                value={String(cfg["ollama_model"] ?? "")}
                onChange={(e) => set("ollama_model", e.target.value)}
                className={inputCls}
                placeholder="qwen2.5"
              />
            </Field>
          </>
        )}

        {isOmni && (
          <>
            <Field label="服务地址" htmlFor="set-omni-host">
              <input
                id="set-omni-host"
                value={String(cfg["omni_host"] ?? "")}
                onChange={(e) => set("omni_host", e.target.value)}
                className={inputCls}
                placeholder="127.0.0.1"
              />
            </Field>
            <div className="flex gap-3">
              <Field label="对话端口" htmlFor="set-omni-chat">
                <input
                  id="set-omni-chat"
                  type="number"
                  value={Number(cfg["omni_chat_port"] ?? 18400)}
                  onChange={(e) => set("omni_chat_port", Number(e.target.value) || 18400)}
                  className={inputCls + " w-28"}
                />
              </Field>
              <Field label="认证端口" htmlFor="set-omni-auth">
                <input
                  id="set-omni-auth"
                  type="number"
                  value={Number(cfg["omni_auth_port"] ?? 18500)}
                  onChange={(e) => set("omni_auth_port", Number(e.target.value) || 18500)}
                  className={inputCls + " w-28"}
                />
              </Field>
            </div>
            <Field label="用户名" htmlFor="set-omni-user">
              <input
                id="set-omni-user"
                value={String(cfg["omni_username"] ?? "admin")}
                onChange={(e) => set("omni_username", e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="密码" htmlFor="set-omni-pass">
              <input
                id="set-omni-pass"
                type="password"
                autoComplete="off"
                value={String(cfg["omni_password"] ?? "")}
                onChange={(e) => set("omni_password", e.target.value)}
                className={inputCls}
                placeholder="admin123"
              />
            </Field>
          </>
        )}

        <datalist id="llm-models">
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            id="btn-test"
            className={btnSecondary}
            disabled={testing}
            onClick={test}
          >
            {testing ? "测试中…" : "测试连接"}
          </button>
          <p className="text-body text-ink-soft">用当前表单值测试，不用先保存</p>
        </div>

        {testResult && (
          <div
            className={`rounded-xl border p-3 ${
              testResult.ok ? "bg-leaf-soft border-leaf" : "bg-clay-soft border-clay"
            }`}
          >
            <p className={`text-ui font-bold ${testResult.ok ? "text-leaf" : "text-clay"}`}>
              {testResult.message}
            </p>
            {testResult.ok && models.length > 0 && (
              <p className="text-body text-ink-soft mt-1">
                模型名已加入「模型」输入框的自动补全
              </p>
            )}
          </div>
        )}
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
