/** useStudyTracker — 进入学习模块自动记录开始，离开自动记录结束 + 进度快照。
 *
 * 用法：
 *   const { recordId, saveSnapshot, endSession } = useStudyTracker("practice", "跟读练习");
 *
 * 续学：从学习记录页跳转时，路由 state 带 { resumeRecordId, resumeSnapshot }
 *       hook 检测到后跳过 start，直接用已有 recordId 继续记录。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../lib/api";

export interface ResumeState {
  resumeRecordId?: string;   // 续学：继续已有记录
  resumeSnapshot?: unknown;   // 续学：从快照恢复进度
  replaySnapshot?: unknown;   // 再来一次：恢复设置但不恢复进度（不续学记录）
}

export default function useStudyTracker(module: string, label: string) {
  const location = useLocation();
  const resume = (location.state as ResumeState | null) ?? {};

  const [recordId, setRecordId] = useState<string | null>(resume.resumeRecordId ?? null);
  // 续学用 resumeSnapshot，再来一次用 replaySnapshot（恢复设置但不恢复进度）
  const [resumeSnapshot] = useState<unknown>(resume.resumeSnapshot ?? resume.replaySnapshot ?? null);
  const isReplay = !!resume.replaySnapshot && !resume.resumeRecordId;
  const startedRef = useRef(false);
  const savedRef = useRef(false); // 防止卸载时重复 end

  // 进入 → 开始记录
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    if (resume.resumeRecordId) {
      // 续学：不需要 start
      return;
    }

    api.studyLogStart(module, label)
      .then((rec) => setRecordId(rec.id))
      .catch((e) => console.warn("[study-tracker] start failed:", e));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 防抖保存快照
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveSnapshot = useCallback((snapshot: unknown, contentSummary?: string) => {
    if (!recordId) return;
    clearTimeout(debounceRef.current!);
    debounceRef.current = setTimeout(() => {
      api.studyLogUpdate(recordId, snapshot, contentSummary).catch(() => {});
    }, 2000);
  }, [recordId]);

  // 结束会话
  const endSession = useCallback((contentSummary: string, snapshot?: unknown, status?: string) => {
    if (!recordId || savedRef.current) return;
    savedRef.current = true;
    clearTimeout(debounceRef.current!);
    api.studyLogEnd(recordId, contentSummary, snapshot, status).catch(() => {});
  }, [recordId]);

  // 页面卸载 → 自动 end（防抖快照可能还没发出去，这里把最新快照一起发）
  const latestSnapshotRef = useRef<unknown>(null);
  const latestSummaryRef = useRef<string>("");

  // 提供一个 setLatest 方法给页面，让它随时更新最新快照引用
  const setLatest = useCallback((snapshot: unknown, summary: string) => {
    latestSnapshotRef.current = snapshot;
    latestSummaryRef.current = summary;
  }, []);

  useEffect(() => {
    return () => {
      // 组件卸载时自动结束
      if (recordId && !savedRef.current) {
        savedRef.current = true;
        clearTimeout(debounceRef.current!);
        // 中途退出标为 active（可续学），用 fetch 兜底
        api.studyLogEnd(recordId, latestSummaryRef.current, latestSnapshotRef.current, "active").catch(() => {});
      }
    };
  }, [recordId]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    recordId,
    resumeSnapshot,
    isReplay,
    saveSnapshot,
    endSession,
    setLatest,
  };
}
