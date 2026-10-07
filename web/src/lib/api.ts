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
  day: number;
  title: string;
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

  // ── 分类速记 ──────────────────────────────────────────────────
  memorizeDays: () => req<{ days: MemorizeDay[] }>("GET", "/api/memorize/days"),
  memorizeDay: (day: number) =>
    req<{ day: number; entries: MemorizeEntry[]; progress: MemorizeDay["progress"] }>(
      "GET",
      `/api/memorize/day/${day}`,
    ),
  memorizeDue: () =>
    req<{ due: { day: number; stage: number; due_date: string }[] }>("GET", "/api/memorize/due"),
  memorizeStart: (day: number) => req<{ ok: boolean }>("POST", "/api/memorize/start", { day }),
  memorizeReview: (day: number) => req<{ ok: boolean }>("POST", "/api/memorize/review", { day }),

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
  readalongTts: (text: string, voice?: string) => {
    const body: Record<string, string> = { text };
    if (voice) body.voice = voice;
    return fetch("/api/readalong/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(async (res) => {
      if (!res.ok) throw new Error("TTS 合成失败");
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    });
  },
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
};
