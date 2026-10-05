import { useEffect, useState } from "react";
import { api, type GroupInfo } from "../lib/api";
import {
  PageHeader, ErrorText, btnPrimary, inputCls,
} from "../components/ui";

/** 导入词库 — 粘贴文本（每行「英文 中文」），生成新分组。 */
export default function ImportPage() {
  const [text, setText] = useState("");
  const [group, setGroup] = useState("");
  const [groups, setGroups] = useState<GroupInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<number | null>(null);

  const refresh = () => {
    api.groups().then((r) => setGroups(r.groups)).catch(() => {});
  };

  useEffect(refresh, []);

  const submit = async () => {
    if (!text.trim()) {
      setError("先粘贴一些词条");
      return;
    }
    const g = group.trim() || `导入 ${new Date().toISOString().slice(0, 10)}`;
    setBusy(true);
    setError("");
    setDone(null);
    try {
      const r = await api.importText(text, g);
      setDone(r.imported);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const removeGroup = async (name: string) => {
    if (!confirm(`删除分组「${name}」及其全部词条？`)) return;
    setError("");
    try {
      await api.deleteGroup(name);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="导入词库" />
      <ErrorText text={error} />
      {done !== null && (
        <p className="text-ui text-leaf font-bold">成功导入 {done} 条</p>
      )}

      <div className="flex flex-col gap-2">
        <label htmlFor="import-text" className="text-ui font-bold">
          词条（每行一条：英文 + 中文）
        </label>
        <textarea
          id="import-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={8}
          placeholder={"apple 苹果\nbanana 香蕉\nHow are you? 你好吗"}
          className={inputCls + " font-mono text-body"}
        />
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="import-group" className="text-ui font-bold">
          分组名（留空自动命名）
        </label>
        <input
          id="import-group"
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          placeholder="比如：三年级上册 Unit 1"
          className={inputCls}
        />
      </div>

      <button className={btnPrimary} disabled={busy} onClick={submit}>
        {busy ? "导入中…" : "导入"}
      </button>

      <div className="flex flex-col gap-2 mt-2">
        <p className="text-ui font-bold">已有分组</p>
        {groups.map((g) => (
          <div
            key={g.name}
            className="bg-card border border-desk-line rounded-lg px-3 py-2 flex items-center gap-2"
          >
            <span className="text-ui font-semibold truncate flex-1">{g.name}</span>
            <span className="text-body text-ink-soft tabular-nums shrink-0">
              {g.count} 条
            </span>
            <button
              type="button"
              onClick={() => removeGroup(g.name)}
              className="text-body text-clay font-bold shrink-0 px-2 py-1 rounded hover:bg-clay-soft"
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
