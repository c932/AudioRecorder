# 跟读教练功能设计

## 概述

跟读教练是一个新子系统，让学生上传 PDF/图片/拍照获取课文原文，TTS 逐句或逐段领读，学生跟读后 GOP 评分+LLM 纠错，低分自动重读，完成后生成总结并加入错题本。

## 用户流程

1. **上传课文**：上传 PDF / 图片 / 拍照 / 粘贴文本
2. **选择模式**：逐句领读 或 逐段领读
3. **跟读循环**：
   - TTS 领读当前句/段（页面高亮当前文本）
   - TTS 播放结束 → 自动切换到录音模式
   - 学生朗读 → 停止录音
   - GOP 评分 + LLM 纠错反馈（通过 TTS 播放）
   - accuracy_score < 80 → 要求重读（最多 2 次）
   - 分数达标或达到重读上限 → 进入下一句/段
4. **完成总结**：LLM 生成总结 + 需复习的词句，低分项自动加入错题本

## 课文显示

- 当前句/段高亮（mango 色），已读灰化，未读正常
- 每句/段下方实时显示中文翻译（LLM 翻译）
- 翻译在跟读开始前批量预取，避免等待

## 领读单位

- **逐句模式**：按句号/问号/感叹号拆分，TTS 播放一句 → 学生跟读一句
- **逐段模式**：按空行或段落标记拆分，TTS 播放一段 → 学生跟读一段
- 用户在开始前选择模式，默认逐句

## 评分与重读

- 评分使用 GOP（`PronunciationCoach.assess()`），只看 `accuracy_score`
- 重读阈值：80 分（< 80 重读）
- 最大重读次数：2 次（即同一句最多读 3 次）
- 重读时 LLM 给出具体纠错建议，通过 TTS 播放

## 错题本集成

- 跟读完成后，得分 < 80 的句子中的词汇自动添加到词库（标记低分），使其出现在错题本 oral 列表
- 通过 `ExerciseManager.add_exercises()` 写入 `words.json`

## 总结

- LLM 生成：整体表现评价、薄弱句列表、需复习的词汇
- 总结页面显示：平均分、总句数、重读次数、薄弱句、需复习词汇

---

## 后端设计

### 新路由：`src/server/routers/readalong.py`

prefix: `/api/readalong`

| 端点 | 方法 | 输入 | 输出 | 说明 |
|------|------|------|------|------|
| `/parse-text` | POST | FormData(file, use_ai) | `{text: str}` | 上传文件提取课文全文 |
| `/start` | POST | `{text: str, mode: "sentence"\|"paragraph"}` | `{session_id: str, segments: [{text, translation}], total: int}` | 开始跟读会话，拆句+翻译 |
| `/tts/{session_id}/{seg_idx}` | POST | - | audio/wav Response | 合成指定段 TTS |
| `/score` | POST | `{session_id: str, seg_idx: int, audio_b64: str, audio_format: str}` | `{score, feedback, llm_feedback, details, should_retry, retry_count}` | 评分+纠错 |
| `/translate` | POST | `{sentences: [str]}` | `{translations: [str]}` | 批量翻译（备用） |
| `/summary` | POST | `{session_id: str, results: [{seg_idx, score, feedback}]}` | `{summary: str, weak_segments, weak_words}` | 生成总结+写入错题本 |
| `/state/{session_id}` | GET | - | `{current_idx, total, scores, mode}` | 会话状态 |

### 新引擎：`src/core/readalong_engine.py`

```python
class ReadAlongEngine:
    """课文跟读引擎：拆句、翻译、总结。"""

    def split_text(text: str, mode: str) -> list[str]:
        """拆分课文为句子或段落列表。"""

    def translate_segments(segments: list[str], config: dict) -> list[str]:
        """批量翻译句子/段落为中文（LLM）。"""

    def generate_summary(results: list[dict], config: dict) -> dict:
        """生成跟读总结，提取薄弱句和需复习词汇。"""
```

### 课文提取

复用 `ContentParser`，但在 `readalong.py` 中用不同的 LLM prompt：

```
Analyze this document and extract the full English text content.
Return the original text as a single string, preserving paragraph breaks.
Ignore page numbers, headers, footers, and non-content elements.
Do NOT extract vocabulary - return the continuous text.
```

### 会话管理

- 使用 `dict` 存储会话状态（单用户局域网场景，内存足够）
- 会话 ID 用 UUID
- 会话包含：原文、拆分结果、翻译、当前索引、得分记录、重读计数

---

## 前端设计

### 新页面：`web/src/pages/ReadAlongPage.tsx`

**四个阶段：**

1. **setup** — 上传文件/粘贴文本，选择模式
2. **readalong** — 主跟读循环
3. **summary** — 跟读总结

**setup 阶段 UI：**
- PageHeader("跟读教练")
- 文件上传区（拖拽或点击选择 PDF/图片）
- 或文本输入框（粘贴课文）
- 模式选择：逐句 / 逐段（chip 按钮，默认逐句）
- 开始按钮

**readalong 阶段 UI：**
- PageHeader("跟读教练", onBack=退出)
- ProgressBar(current, total)
- 课文显示区（卡片）：
  - 当前句/段高亮（text-mango-dk font-bold）
  - 已读句 text-ink-soft/60
  - 未读句 text-ink
  - 每句下方中文翻译 text-body text-ink-soft
- 领读状态指示器（播放图标 + "听标准音" 按钮）
- RecordButton
- 评分结果区（ScoreResultView + LLM 纠错文字）
- 低分重读提示条（bg-clay-soft border-clay）

**summary 阶段 UI：**
- 居中大分数（平均分）
- 统计：总句数、重读次数
- 薄弱句列表（clay 标记）
- 需复习词汇
- 返回按钮

**跟读循环状态机：**
```
idle → playing (TTS 领读) → waiting (等待录音) → recording → scoring → scored
  scored → (score >= 80 || retries >= 2) → idle (下一句)
  scored → (score < 80 && retries < 2) → waiting (重读)
```

### API 扩展：`web/src/lib/api.ts`

新增接口：
```typescript
interface ReadAlongSegment {
  text: string;
  translation: string;
}

interface ReadAlongSession {
  session_id: string;
  segments: ReadAlongSegment[];
  total: number;
  mode: "sentence" | "paragraph";
}

interface ReadAlongScoreResult {
  score: number;
  feedback: string;
  llm_feedback: string;
  details: ScoreResult;
  should_retry: boolean;
  retry_count: number;
}

interface ReadAlongSummary {
  summary: string;
  weak_segments: ReadAlongSegment[];
  weak_words: string[];
}
```

### 路由与导航

- App.tsx 新增路由：`/readalong` → ReadAlongPage
- HomePage.tsx 口语训练卡片下增加子项：`{ to: "/readalong", zh: "跟读教练" }`

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/server/routers/readalong.py` | 新增 | 后端跟读教练路由 |
| `src/core/readalong_engine.py` | 新增 | 拆句、翻译、总结引擎 |
| `web/src/pages/ReadAlongPage.tsx` | 新增 | 前端跟读教练页面 |
| `web/src/lib/api.ts` | 修改 | 新增 readalong API 接口 |
| `web/src/App.tsx` | 修改 | 新增 `/readalong` 路由 |
| `web/src/pages/HomePage.tsx` | 修改 | 口语训练增加跟读教练入口 |
| `src/server/web_server.py` | 修改 | 注册 readalong 路由 |
