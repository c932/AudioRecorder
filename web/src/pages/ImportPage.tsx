import { useEffect, useRef, useState } from "react";
import { api, type GroupInfo, type ParsedItem } from "../lib/api";
import {
  PageHeader, ErrorText, btnPrimary, btnSecondary, inputCls, Spinner,
} from "../components/ui";

/** 导入词库 — 文件上传（PDF/TXT/图片，AI 解析预览编辑）或粘贴文本。 */
export default function ImportPage() {
  const [tab, setTab] = useState<"file" | "text">("file");
  const [text, setText] = useState("");
  const [group, setGroup] = useState("");
  const [groups, setGroups] = useState<GroupInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<number | null>(null);

  // 文件模式：解析 → 预览表格（可编辑）→ 导入
  const [useAi, setUseAi] = useState(true);
  const [items, setItems] = useState<ParsedItem[] | null>(null);
  const [progress, setProgress] = useState("");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const imageRef = useRef<HTMLInputElement>(null);
  const docRef = useRef<HTMLInputElement>(null);

  const refresh = () => {
    api.groups().then((r) => setGroups(r.groups)).catch(() => {});
  };

  useEffect(refresh, []);

  const setCell = (i: number, key: keyof ParsedItem, value: string) => {
    setItems((arr) =>
      arr ? arr.map((it, idx) => (idx === i ? { ...it, [key]: value } : it)) : arr,
    );
  };

  const removeRow = (i: number) => {
    setItems((arr) => (arr ? arr.filter((_, idx) => idx !== i) : arr));
  };

  /** 从 input 追加图片到待解析列表 */
  const addImages = (files: FileList | File[]) => {
    const images = Array.from(files).filter((f) => f.type.startsWith("image/"));
    if (images.length === 0) return;
    setPendingFiles((prev) => [...prev, ...images]);
  };

  const removePending = (i: number) => {
    setPendingFiles((prev) => prev.filter((_, idx) => idx !== i));
  };

  /** 逐个解析待选文件，合并结果到同一预览；单个失败不阻断整体。 */
  const parsePending = async () => {
    if (pendingFiles.length === 0) return;
    if (pendingFiles.length === 1) {
      setGroup(pendingFiles[0].name.replace(/\.[^.]+$/, ""));
    } else {
      setGroup(pendingFiles[0].name.replace(/\.[^.]+$/, ""));
    }
    setItems(null);
    setDone(null);
    setError("");
    setBusy(true);

    const allItems: ParsedItem[] = [];
    const errors: string[] = [];

    for (let i = 0; i < pendingFiles.length; i++) {
      setProgress(`正在解析第 ${i + 1}/${pendingFiles.length} 张图片…`);
      try {
        const r = await api.parseFile(pendingFiles[i], true);
        allItems.push(...r.items);
      } catch (e) {
        errors.push(`${pendingFiles[i].name}: ${(e as Error).message}`);
      }
    }

    setItems(allItems.length > 0 ? allItems : null);
    if (errors.length > 0) {
      if (allItems.length === 0) {
        setError(`全部图片解析失败：${errors.join("；")}`);
      } else {
        setError(`${errors.length} 张图片解析失败（已跳过）：${errors.join("；")}`);
      }
    }
    setBusy(false);
    setProgress("");
    setPendingFiles([]);
    if (imageRef.current) imageRef.current.value = "";
    if (docRef.current) docRef.current.value = "";
  };

  /** 解析单个 PDF/TXT 文件 */
  const pickDoc = async (f: File) => {
    setGroup(f.name.replace(/\.[^.]+$/, ""));
    setItems(null);
    setDone(null);
    setError("");
    setBusy(true);
    try {
      const r = await api.parseFile(f, useAi);
      setItems(r.items);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (docRef.current) docRef.current.value = "";
    }
  };

  const importParsed = async () => {
    if (!items || items.length === 0) return;
    const g = group.trim() || `导入 ${new Date().toISOString().slice(0, 10)}`;
    setBusy(true);
    setError("");
    setDone(null);
    try {
      const r = await api.importItems(items, g);
      setDone(r.imported);
      setItems(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitText = async () => {
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

      {/* 模式切换 */}
      <div className="flex gap-2">
        {(["file", "text"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => {
              setTab(t);
              setError("");
            }}
            className={
              (tab === t ? btnPrimary : btnSecondary) + " text-ui px-4 py-2"
            }
          >
            {t === "file" ? "上传文件" : "粘贴文本"}
          </button>
        ))}
      </div>

      {tab === "file" ? (
        <div className="flex flex-col gap-3">
          {/* ── 图片导入（累积模式，兼容不支持多选的手机） ── */}
          <label
            htmlFor="import-images"
            className="border-2 border-dashed border-desk-line rounded-xl px-4 py-5 text-center cursor-pointer hover:border-mango transition-colors"
          >
            <p className="text-ui font-bold">📷 添加图片</p>
            <p className="text-body text-ink-soft mt-1">
              点此选择图片，可多次添加，选好后点下方按钮解析
            </p>
          </label>
          <input
            ref={imageRef}
            id="import-images"
            type="file"
            accept="image/*"
            className="sr-only"
            onChange={(e) => {
              if (e.target.files) addImages(e.target.files);
              // 清空 value 以便再次选同名文件
              e.target.value = "";
            }}
          />

          {/* 待解析图片列表 */}
          {pendingFiles.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <p className="text-ui font-bold">
                已选 {pendingFiles.length} 张图片
              </p>
              {pendingFiles.map((f, i) => (
                <div
                  key={`${f.name}-${i}`}
                  className="bg-card border border-desk-line rounded-lg px-3 py-2 flex items-center gap-2"
                >
                  <span className="text-body flex-1 truncate">{f.name}</span>
                  <span className="text-body text-ink-soft tabular-nums shrink-0">
                    {(f.size / 1024).toFixed(0)} KB
                  </span>
                  <button
                    type="button"
                    onClick={() => removePending(i)}
                    className="text-body text-clay font-bold shrink-0 px-1.5"
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                className={btnPrimary}
                disabled={busy}
                onClick={parsePending}
              >
                {busy ? "解析中…" : `开始解析 ${pendingFiles.length} 张图片`}
              </button>
            </div>
          )}

          {/* ── PDF / TXT 文件导入 ── */}
          <label
            htmlFor="import-doc"
            className="border-2 border-dashed border-desk-line rounded-xl px-4 py-5 text-center cursor-pointer hover:border-mango transition-colors"
          >
            <p className="text-ui font-bold">📄 选择 PDF / TXT 文件</p>
            <p className="text-body text-ink-soft mt-1">
              适合整本词表或扫描版课本
            </p>
          </label>
          <input
            ref={docRef}
            id="import-doc"
            type="file"
            accept=".pdf,.txt"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) pickDoc(f);
            }}
          />

          <label className="flex items-center gap-2 text-ui font-semibold">
            <input
              type="checkbox"
              checked={useAi}
              onChange={(e) => setUseAi(e.target.checked)}
              className="w-4 h-4 accent-mango"
            />
            AI 智能解析（图片/PDF 必须开启）
          </label>

          {busy && <Spinner label={progress || "AI 解析中，可能要一分钟…"} />}

          {items && (
            <div className="flex flex-col gap-3">
              <div className="flex items-baseline justify-between">
                <p className="text-ui font-bold">
                  解析到 {items.length} 条 — 检查后导入
                </p>
                <button
                  type="button"
                  className="text-body text-clay font-bold"
                  onClick={() => setItems(null)}
                >
                  丢弃
                </button>
              </div>
              <div className="flex flex-col gap-1.5 max-h-[50vh] overflow-y-auto">
                {items.map((it, i) => (
                  <div
                    key={i}
                    className="bg-card border border-desk-line rounded-lg px-2 py-1.5 flex items-center gap-1.5"
                  >
                    <input
                      value={it.text}
                      onChange={(e) => setCell(i, "text", e.target.value)}
                      aria-label={`第 ${i + 1} 条英文`}
                      className="flex-1 min-w-0 bg-transparent text-ui font-semibold focus:outline-none"
                    />
                    <input
                      value={it.phonetic}
                      onChange={(e) => setCell(i, "phonetic", e.target.value)}
                      aria-label={`第 ${i + 1} 条音标`}
                      placeholder="音标"
                      className="w-24 bg-transparent text-body text-ink-soft focus:outline-none"
                    />
                    <input
                      value={it.translation}
                      onChange={(e) => setCell(i, "translation", e.target.value)}
                      aria-label={`第 ${i + 1} 条释义`}
                      placeholder="中文"
                      className="flex-1 min-w-0 bg-transparent text-body text-ink-soft focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => removeRow(i)}
                      aria-label="删除这一条"
                      className="text-body text-clay font-bold px-1.5 shrink-0"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-2">
                <label htmlFor="import-group" className="text-ui font-bold">
                  分组名
                </label>
                <input
                  id="import-group"
                  value={group}
                  onChange={(e) => setGroup(e.target.value)}
                  placeholder="比如：三年级上册 Unit 1"
                  className={inputCls}
                />
              </div>
              <button
                className={btnPrimary}
                disabled={busy || items.length === 0}
                onClick={importParsed}
              >
                {busy ? "导入中…" : `导入 ${items.length} 条`}
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
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
          <button className={btnPrimary} disabled={busy} onClick={submitText}>
            {busy ? "导入中…" : "导入"}
          </button>
        </div>
      )}

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
