// API client — 少儿英语发音教练 Web 后端（FastAPI）全部接口。

export interface WordItem {
  text: string;
  phonetic?: string;
  translation?: string;
  group?: string;
  pos?: string;
  quiz_wrong?: number;
  quiz_correct?: number;
  last_score?: number;
  times_practiced?: number;
}

export interface GroupInfo {
  name: string;
  count: number;
}

export interface PhonemeScore {
  phoneme: string;
  score: number;
  start: number;
  end: number;
  alignment_confidence: number;
  low_confidence: boolean;
}

export interface WordScore {
  word: string;
  score: number;
  phonemes: PhonemeScore[];
}

export interface GopError {
  type: string;
  expected: string;
  actual: string;
  word: string;
  position: number;
}

export interface ScoreResult {
  accuracy_score: number;
  fluency_score: number;
  completeness_score: number;
  feedback: string;
  details: {
    scoring_method: string;
    recognized: string;
    reference: string;
    words: WordScore[];
    errors: GopError[];
  };
}

export interface QuizQuestion {
  type: "zh2en" | "en2zh";
  question_text: string;
  answers?: string[];
  answer?: string;
  options?: string[] | null;
  correct_index?: number | null;
  chinese_hint?: string | null;
  source_item?: WordItem;
}

export interface OralBank {
  id: string;
  name: string;
  sentence_count?: number;
  created_at?: string;
  sentences?: OralSentence[];
}

export interface OralSentence {
  type: string;
  text: string;
  translation: string;
  source_word?: string;
  source_group?: string;
}

export interface ScenarioBank {
  id: string;
  name: string;
  source_groups: string[];
  turn_count: number;
  created_at: string;
  script: { role: "A" | "B"; text: string; translation: string }[];
}

export interface TutorState {
  phase: string;
  word: string;
  translation: string;
  word_index: number;
  total_words: number;
  topic: string;
  in_retry: boolean;
  retry_queue_size: number;
  mastery: Record<string, number | boolean>;
}

export interface TutorAction {
  action: string;
  text: string;
  tts_text?: string;
  tts_token?: string;  // 预合成音频 token，播放用 /api/tutor/tts/{token}
  options?: string[];
  grammar_correct?: boolean;
  correction?: string | null;
  meaning_correct?: boolean;
}

export interface TutorResponse {
  actions: TutorAction[];
  state: TutorState;
  score?: number;
  feedback?: string;
  recognized?: string;
  error?: string;
}

export interface MemorizeProgress {
  stage: number;
  total_stages: number;
  start_date: string;
  next_due: string | null;
  last_review: string;
  last_test: unknown;
}

export interface MemorizeDay {
  key: string;       // "d1"~"d28" for builtin, "v:groupName" for vocab
  title: string;
  source: string;    // "builtin" | "vocab"
  count: number;
  started: boolean;
  progress: MemorizeProgress | null;
}

export interface MemorizeEntry {
  text: string;
  pos: string;
  translation: string;
  category: string;
}

/** 统一出题引擎的题目结构（/api/memorize/quiz 返回，供学习中心复习使用）。 */
export interface ReviewQuestion {
  type: "en2zh" | "zh2en";
  mode: "en2cn" | "cn2en" | "fill";
  source_item: {
    text: string;
    translation?: string;
    pos?: string;
    group?: string;
  };
  question_text: string;
  question_extra?: string;
  options: string[] | null;
  answer: string | null;
  answers: string[] | null;
  correct_index: number | null;
  chinese_hint?: string | null;
}

export interface ParsedItem {
  text: string;
  phonetic: string;
  translation: string;
}

export interface ReadAlongSegment {
  text: string;
  translation: string;
}

export interface ReadAlongSession {
  session_id: string;
  segments: ReadAlongSegment[];
  total: number;
  mode: "sentence" | "paragraph";
}

export interface ReadAlongScoreResult {
  score: number;
  feedback: string;
  llm_feedback: string;
  details: ScoreResult;
  should_retry: boolean;
  retry_count: number;
}

export interface ReadAlongSummary {
  summary: string;
  avg_score: number;
  weak_segments: ReadAlongSegment[];
  weak_words: string[];
  total_segments: number;
  total_retries: number;
}

export interface StudyRecord {
  id: string;
  module: string;
  module_label: string;
  status: "active" | "completed" | "abandoned";
  started_at: string;
  ended_at: string | null;
  duration_sec: number;
  content_summary: string;
  snapshot: unknown;
}

export interface StudyStats {
  today_sec: number;
  week_sec: number;
  month_sec: number;
  total_count: number;
  streak_days: number;
  module_breakdown: Record<string, number>;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const j = await res.json();
      if (j?.detail) detail = String(j.detail);
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

/** multipart 上传（浏览器自动设 boundary，不能手动设 Content-Type）。 */
async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: "POST", body: form });
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const j = await res.json();
      if (j?.detail) detail = String(j.detail);
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  // ── 词库 ──────────────────────────────────────────────────────
  groups: () => req<{ groups: GroupInfo[] }>("GET", "/api/vocab/groups"),
  words: (group?: string) =>
    req<{ items: WordItem[] }>("GET", `/api/vocab/words${group ? `?group=${encodeURIComponent(group)}` : ""}`),
  importText: (text: string, group: string) =>
    req<{ imported: number }>("POST", "/api/vocab/import-text", { text, group }),
  parseFile: (file: File, useAi: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("use_ai", String(useAi));
    return postForm<{ items: ParsedItem[] }>("/api/vocab/parse-file", form);
  },
  importItems: (items: ParsedItem[], group: string) =>
    req<{ imported: number }>("POST", "/api/vocab/import-items", { items, group }),
  deleteGroup: (name: string) =>
    req<{ deleted: string }>("DELETE", `/api/vocab/group/${encodeURIComponent(name)}`),

  // ── 发音练习 ──────────────────────────────────────────────────
  practiceSession: (count: number) =>
    req<{ items: WordItem[]; total: number }>("GET", `/api/practice/session?count=${count}`),
  score: (audio_b64: string, audio_format: string, reference: string) =>
    req<ScoreResult>("POST", "/api/practice/score", { audio_b64, audio_format, reference }),

  // ── 中英互译 ──────────────────────────────────────────────────
  quizStart: (groups: string[], count: number) =>
    req<{ questions: QuizQuestion[]; total: number }>("POST", "/api/quiz/start", { groups, count }),
  quizAnswer: (question: QuizQuestion, user_answer: string | string[]) =>
    req<{ is_correct: boolean; correct_answer: string | string[] }>("POST", "/api/quiz/answer", { question, user_answer }),

  // ── 口语测试 ──────────────────────────────────────────────────
  oralBanks: () => req<{ banks: OralBank[] }>("GET", "/api/oral/banks"),
  oralGenerate: (groups: string[], count: number) =>
    req<{ bank: OralBank }>("POST", "/api/oral/generate", { groups, count }),
  oralBankSentences: (id: string) =>
    req<{ sentences: OralSentence[] }>("GET", `/api/oral/bank/${encodeURIComponent(id)}/sentences`),

  // ── 情景会话 ──────────────────────────────────────────────────
  scenarioBanks: () => req<{ banks: ScenarioBank[] }>("GET", "/api/scenario/banks"),
  scenarioGenerate: (groups: string[], turn_count?: number) =>
    req<{ bank: ScenarioBank }>("POST", "/api/scenario/generate", { groups, turn_count }),
  scenarioGenerateFromItems: (items: WordItem[], turn_count?: number) =>
    req<{ bank: ScenarioBank }>("POST", "/api/scenario/generate-from-items", { items, turn_count }),
  scenarioSummary: (
    session_results: { turn_idx: number; text: string; score: number }[],
    scenario_title: string,
  ) => req<{ summary: string }>("POST", "/api/scenario/summary", { session_results, scenario_title }),

  // ── AI 家教 ──────────────────────────────────────────────────
  tutorStart: (topic: string, vocabulary: WordItem[]) =>
    req<TutorResponse>("POST", "/api/tutor/start", { topic, vocabulary }),
  tutorPronunciation: (audio_b64: string, audio_format: string) =>
    req<TutorResponse>("POST", "/api/tutor/pronunciation", { audio_b64, audio_format }),
  tutorAnswer: (audio_b64: string, audio_format: string) =>
    req<TutorResponse>("POST", "/api/tutor/answer", { audio_b64, audio_format }),
  tutorText: (text: string) => req<TutorResponse>("POST", "/api/tutor/text", { text }),
  tutorChoice: (chosen: string, correct: string) =>
    req<TutorResponse>("POST", "/api/tutor/choice", { chosen, correct }),
  tutorState: () => req<{ state: TutorState }>("GET", "/api/tutor/state"),
  tutorSummary: () =>
    req<{
      topic: string;
      total_words: number;
      mastered: number;
      weak_words: string[];
      word_mastery: Record<string, Record<string, number | boolean>>;
    }>("GET", "/api/tutor/summary"),
  tutorStop: () => req<{ ok: boolean }>("POST", "/api/tutor/stop"),

  // ── 学习中心（原分类速记） ──────────────────────────────────────
  memorizeDays: () => req<{ days: MemorizeDay[] }>("GET", "/api/memorize/days"),
  memorizeModule: (key: string) =>
    req<{ key: string; entries: MemorizeEntry[]; progress: MemorizeProgress | null }>(
      "GET",
      `/api/memorize/module?key=${encodeURIComponent(key)}`,
    ),
  memorizeDue: () =>
    req<{ due: { key: string; stage: number; due_date: string }[] }>("GET", "/api/memorize/due"),
  memorizeStart: (key: string) => req<{ ok: boolean }>("POST", "/api/memorize/start", { key }),
  memorizeReview: (key: string) => req<{ ok: boolean }>("POST", "/api/memorize/review", { key }),
  memorizeQuiz: (key: string, mode: "en2cn" | "cn2en" | "fill") =>
    req<{ questions: ReviewQuestion[]; total: number; mode: string }>("POST", "/api/memorize/quiz", { key, mode }),
  memorizeAnswer: (question: ReviewQuestion, user_answer: string | string[]) =>
    req<{ is_correct: boolean; correct_answer: string | string[] }>(
      "POST", "/api/memorize/answer", { question, user_answer },
    ),

  // ── 错题本 / 配置 ─────────────────────────────────────────────
  mistakes: () => req<{ oral: WordItem[]; quiz: WordItem[] }>("GET", "/api/mistakes"),
  config: () => req<Record<string, unknown>>("GET", "/api/config"),
  saveConfig: (config: Record<string, unknown>) =>
    req<{ ok: boolean }>("PUT", "/api/config", { config }),
  testConfig: (config: Record<string, unknown>) =>
    req<{ ok: boolean; message: string; models?: string[] }>(
      "POST", "/api/config/test", { config }),

  // ── 跟读教练 ──────────────────────────────────────────────────
  readalongParseFile: (file: File, useAi: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("use_ai", String(useAi));
    return postForm<{ text: string }>("/api/readalong/parse-text", form);
  },
  readalongStart: (text: string, mode: "sentence" | "paragraph") =>
    req<ReadAlongSession>("POST", "/api/readalong/start", { text, mode }),
  readalongStartText: (text: string) =>
    req<ReadAlongSession>("POST", "/api/readalong/start-text", { text }),
  readalongScore: (
    session_id: string,
    seg_idx: number,
    audio_b64: string,
    audio_format: string,
  ) =>
    req<ReadAlongScoreResult>("POST", "/api/readalong/score", {
      session_id,
      seg_idx,
      audio_b64,
      audio_format,
    }),
  readalongSummary: (session_id: string) =>
    req<ReadAlongSummary>("POST", "/api/readalong/summary", { session_id }),
  readalongState: (session_id: string) =>
    req<{ session_id: string; segments: ReadAlongSegment[]; total: number; mode: string; current_idx: number; results: Record<string, { score: number; retries: number }> }>("GET", `/api/readalong/state/${encodeURIComponent(session_id)}`),

  // ── 学习记录 ──────────────────────────────────────────────────
  studyLogStart: (module: string, module_label: string) =>
    req<StudyRecord>("POST", "/api/study-log/start", { module, module_label }),
  studyLogUpdate: (record_id: string, snapshot?: unknown, content_summary?: string) =>
    req<{ ok: boolean }>("PUT", `/api/study-log/update/${record_id}`, {
      snapshot: snapshot ?? null,
      content_summary: content_summary ?? "",
    }),
  studyLogEnd: (record_id: string, content_summary?: string, snapshot?: unknown, status?: string) =>
    req<StudyRecord>("POST", `/api/study-log/end/${record_id}`, {
      content_summary: content_summary ?? "",
      snapshot: snapshot ?? null,
      status: status ?? "completed",
    }),
  studyLogRecords: (params?: { module?: string; status?: string; date_from?: string; date_to?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.module) qs.set("module", params.module);
    if (params?.status) qs.set("status", params.status);
    if (params?.date_from) qs.set("date_from", params.date_from);
    if (params?.date_to) qs.set("date_to", params.date_to);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    const s = qs.toString();
    return req<{ records: StudyRecord[] }>("GET", `/api/study-log/records${s ? `?${s}` : ""}`);
  },
  studyLogStats: () => req<StudyStats>("GET", "/api/study-log/stats"),
  studyLogDelete: (record_id: string) =>
    req<{ ok: boolean }>("DELETE", `/api/study-log/${record_id}`),
};
