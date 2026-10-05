"""
QuizEngine - Translation quiz question generation, validation, and scoring.
Uses LLM to generate fill-in-the-blank and multiple-choice questions.
Supports pre-generated quiz banks for instant quiz start.
"""
import re
import json
import random
import threading
import copy
import os
from datetime import datetime
from src.core.qt_compat import QObject, pyqtSignal

from src.core.content_parser import _get_llm_client_and_model
from src.utils import get_user_data_path


class QuizEngine(QObject):
    """Generates and manages translation quiz questions."""
    
    questions_ready = pyqtSignal(list)      # Emitted when all questions are generated
    generation_error = pyqtSignal(str)       # Emitted on LLM error
    progress_update = pyqtSignal(int, int)   # Emitted: (generated_count, total_count)
    
    # Bank generation signals
    bank_progress_update = pyqtSignal(int, int)   # (generated_count, total_count)
    bank_generation_done = pyqtSignal(dict)        # Full bank dict
    bank_generation_error = pyqtSignal(str)        # Error message
    
    BATCH_SIZE = 5  # Questions per LLM call
    
    def __init__(self, exercise_manager):
        super().__init__()
        self.exercise_manager = exercise_manager
        self.questions = []
        self.session_results = []
        self.current_index = 0
        self._generating_bank = False  # Flag to distinguish bank generation from quiz generation
    
    def start_quiz(self, groups, count: int):
        """
        Start quiz generation: select words, assign types, generate questions via LLM.
        Runs LLM calls in background threads.
        
        Args:
            groups: A single group name (str) or a list of group names.
            count: Total number of questions to generate.
        """
        self.questions = []
        self.session_results = []
        self.current_index = 0
        
        # Normalize groups to list
        if isinstance(groups, str):
            groups = [groups]
        
        # 1. Get words from the selected group(s)
        all_words = self.exercise_manager.exercises.get("words", [])
        group_words = [w for w in all_words if w.get('group', 'Default') in groups]
        
        if not group_words:
            self.generation_error.emit(f"No words found in selected groups.")
            return
        
        # Adjust count if group has fewer words
        actual_count = min(count, len(group_words))
        
        # 2. Randomly select words
        selected = random.sample(group_words, actual_count)
        
        # 3. Assign question types (roughly 1:1 zh2en : en2zh, randomly mixed)
        random.shuffle(selected)
        half = actual_count // 2
        type_assignments = []
        for i, item in enumerate(selected):
            if i < half:
                type_assignments.append(("en2zh", item))
            else:
                type_assignments.append(("zh2en", item))
        random.shuffle(type_assignments)
        
        # 4. Separate into: single-word zh2en (no LLM) and LLM-needed batches
        local_questions = []  # Single-word zh2en, generated locally
        llm_zh2en_items = []  # Phrase zh2en, needs fill-in-the-blank
        llm_en2zh_items = []  # en2zh, needs multiple choice
        
        for qtype, item in type_assignments:
            text = item.get("text", "")
            if qtype == "zh2en" and " " not in text.strip():
                # Single word - generate locally
                local_questions.append({
                    "type": "zh2en",
                    "source_item": item,
                    "question_text": item.get("translation", ""),
                    "answers": [text],
                    "options": None,
                    "correct_index": None,
                    "chinese_hint": None,
                })
            elif qtype == "zh2en":
                llm_zh2en_items.append(item)
            else:
                llm_en2zh_items.append(item)
        
        # Add local questions immediately
        self.questions.extend(local_questions)
        
        # 5. Generate LLM questions in background
        total_llm = len(llm_zh2en_items) + len(llm_en2zh_items)
        self._pending_batches = 0
        self._local_count = len(local_questions)
        self._total_expected = actual_count
        
        if total_llm == 0:
            # All local, no LLM needed
            random.shuffle(self.questions)
            self.questions_ready.emit(self.questions)
            return
        
        # Batch LLM items
        batches = []
        for i in range(0, len(llm_zh2en_items), self.BATCH_SIZE):
            batch = llm_zh2en_items[i:i + self.BATCH_SIZE]
            batches.append(("zh2en", batch))
        for i in range(0, len(llm_en2zh_items), self.BATCH_SIZE):
            batch = llm_en2zh_items[i:i + self.BATCH_SIZE]
            batches.append(("en2zh", batch))
        
        self._pending_batches = len(batches)
        self.progress_update.emit(len(local_questions), actual_count)
        
        # Launch background threads for each batch
        for qtype, batch_items in batches:
            t = threading.Thread(
                target=self._generate_batch,
                args=(qtype, batch_items),
                daemon=True
            )
            t.start()
    
    def _generate_batch(self, qtype: str, items: list):
        """Generate a batch of questions via LLM (runs in background thread)."""
        try:
            config_path = get_user_data_path("config.json")
            config = {}
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
            
            client, model = _get_llm_client_and_model(config)
            
            if qtype == "zh2en":
                questions = self._generate_fill_blank(client, model, items)
            else:
                questions = self._generate_multiple_choice(client, model, items)
            
            self.questions.extend(questions)
            self._pending_batches -= 1
            
            if self._generating_bank:
                self.bank_progress_update.emit(len(self.questions), self._total_expected)
            else:
                self.progress_update.emit(len(self.questions), self._total_expected)
            
            # All batches done?
            if self._pending_batches <= 0:
                random.shuffle(self.questions)
                if self._generating_bank:
                    self._finish_bank_generation()
                else:
                    self.questions_ready.emit(self.questions)
                
        except Exception as e:
            print(f"[QuizEngine] Batch generation error: {e}")
            self._pending_batches -= 1
            if self._pending_batches <= 0:
                if self.questions:
                    random.shuffle(self.questions)
                    if self._generating_bank:
                        self._finish_bank_generation()
                    else:
                        self.questions_ready.emit(self.questions)
                else:
                    if self._generating_bank:
                        self.bank_generation_error.emit(f"Question generation failed: {e}")
                    else:
                        self.generation_error.emit(f"Question generation failed: {e}")
    
    def _generate_fill_blank(self, client, model: str, items: list) -> list:
        """Generate fill-in-the-blank questions for phrases."""
        # Read blank count from config
        config_path = get_user_data_path("config.json")
        blank_count = 1
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    cfg = json.load(f)
                    blank_count = cfg.get("quiz_blank_count", 1)
            except Exception:
                pass
        
        item_list = "\n".join([
            f'{i+1}. "{item["text"]}" (中文: {item.get("translation", "")})'
            for i, item in enumerate(items)
        ])
        
        if blank_count == 1:
            blank_rule = "Replace exactly 1 word — the most educationally valuable (key vocabulary) — with (1)______"
            format_example = '[{{"index": 0, "full_sentence": "I keep a diary every night.", "blanked_sentence": "I (1)______ a diary every night.", "answers": ["keep"], "chinese_sentence": "我每天晚上记日记。"}}]'
        else:
            blank_rule = (
                f"Replace exactly {blank_count} SEPARATE words with numbered blanks (1)______, (2)______, etc.\n"
                "   - Choose {n} non-adjacent words if possible (spread across the sentence).\n"
                "   - Pick the most challenging/complex words that test vocabulary knowledge.\n"
                "   - Each blank should be a single word (not a phrase).\n"
                "   - The answers array must list the words in blank order (1), (2), etc."
            ).format(n=blank_count)
            format_example = f'[{{"index": 0, "full_sentence": "She always keeps a diary and writes stories.", "blanked_sentence": "She always (1)______ a diary and (2)______ stories.", "answers": ["keeps", "writes"], "chinese_sentence": "她总是记日记并写故事。"}}]'
        
        prompt = f"""You are an English quiz expert for children. Generate fill-in-the-blank questions for the following English phrases.

Phrase list:
{item_list}

Rules:
1. For each phrase, create a simple example sentence containing the phrase (suitable for children).
2. {blank_rule}
3. CRITICAL: The blanked words (answers) must be plain English words only — letters, no symbols. NEVER use symbols like ℃, °, ℉, $, %, etc. as answers. If the phrase contains such symbols, rewrite the sentence to avoid them (e.g., "40.3 degrees" instead of "40.3°C").
4. Provide a natural Chinese translation of the FULL sentence (chinese_sentence field). This helps students understand the context.
5. Return ONLY a JSON array, no other text.
6. Format: {format_example}

Return JSON:"""
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.3
            )
            content = response.choices[0].message.content.strip()
            parsed = self._parse_json_array(content)
            
            questions = []
            for i, item in enumerate(items):
                # Find matching result from LLM
                llm_result = None
                for r in parsed:
                    if r.get("index") == i:
                        llm_result = r
                        break
                
                if llm_result:
                    # Support both old "answer" and new "answers" format
                    answers = llm_result.get("answers", None)
                    if answers is None:
                        ans = llm_result.get("answer", item["text"].split()[-1])
                        answers = [ans] if isinstance(ans, str) else ans
                    
                    # Skip questions with non-English answers (e.g. ℃, °)
                    if not self._is_valid_english_answer(answers):
                        print(f"[QuizEngine] Skipping non-English answer: {answers} for '{item['text']}'")
                        # Use local fallback for this item instead
                        words = item["text"].split()
                        if " " in item["text"]:
                            sorted_w = sorted(words, key=len, reverse=True)
                            to_blank = sorted_w[:1]
                            blanked = item["text"]
                            fb_answers = []
                            for w in to_blank:
                                blanked = blanked.replace(w, "(1)______", 1)
                                fb_answers.append(w)
                            questions.append({
                                "type": "zh2en",
                                "source_item": item,
                                "question_text": blanked,
                                "answers": fb_answers,
                                "options": None,
                                "correct_index": None,
                                "chinese_hint": item.get("translation", ""),
                            })
                        # If single word, skip entirely (shouldn't happen here)
                        continue
                    
                    # Use LLM-generated full sentence Chinese translation, fallback to phrase translation
                    chinese_hint = llm_result.get("chinese_sentence", "") or item.get("translation", "")
                    
                    questions.append({
                        "type": "zh2en",
                        "source_item": item,
                        "question_text": llm_result.get("blanked_sentence", ""),
                        "answers": answers,
                        "options": None,
                        "correct_index": None,
                        "chinese_hint": chinese_hint,
                    })
                else:
                    # Fallback: blank the last word of the phrase
                    words = item["text"].split()
                    answer = words[-1] if words else item["text"]
                    blanked = item["text"].rsplit(answer, 1)[0] + "(1)______"
                    questions.append({
                        "type": "zh2en",
                        "source_item": item,
                        "question_text": blanked,
                        "answers": [answer],
                        "options": None,
                        "correct_index": None,
                        "chinese_hint": item.get("translation", ""),
                    })
            
            return questions
            
        except Exception as e:
            print(f"[QuizEngine] Fill-blank LLM error: {e}")
            # Fallback: generate simple local questions
            return self._fallback_fill_blank(items)
    
    @staticmethod
    def _is_valid_english_answer(answers: list) -> bool:
        """Check if all answers contain only typable English characters.
        Rejects answers with non-ASCII symbols like ℃, °, ℉, etc.
        """
        import re
        pattern = re.compile(r"^[a-zA-Z0-9\s\.\,\-\']+$")
        for a in answers:
            if not a or not pattern.match(a.strip()):
                return False
        return True
    
    def _fallback_fill_blank(self, items: list) -> list:
        """Fallback: generate fill-in-blank without LLM."""
        # Read blank count from config
        import os
        config_path = get_user_data_path("config.json")
        blank_count = 1
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    cfg = json.load(f)
                    blank_count = cfg.get("quiz_blank_count", 1)
            except Exception:
                pass
        
        questions = []
        for item in items:
            words = item["text"].split()
            # Blank the N longest words (spread apart if possible)
            sorted_words = sorted(words, key=len, reverse=True)
            to_blank = sorted_words[:min(blank_count, len(sorted_words))]
            
            blanked = item["text"]
            answers = []
            for idx, w in enumerate(to_blank):
                blanked = blanked.replace(w, f"({idx+1})______", 1)
                answers.append(w)
            
            questions.append({
                "type": "zh2en",
                "source_item": item,
                "question_text": blanked,
                "answers": answers,
                "options": None,
                "correct_index": None,
                "chinese_hint": item.get("translation", ""),
            })
        return questions
    
    def _generate_multiple_choice(self, client, model: str, items: list) -> list:
        """Generate multiple-choice questions for en2zh."""
        item_list = "\n".join([
            f'{i+1}. "{item["text"]}" (中文: {item.get("translation", "")})'
            for i, item in enumerate(items)
        ])
        
        prompt = f"""You are an English quiz expert for children. Generate multiple-choice questions (English to Chinese) for the following words/phrases.

Word list:
{item_list}

CRITICAL Rules for distractors:
1. For each word/phrase, generate exactly 4 Chinese options (A/B/C/D).
2. 1 correct answer + 3 distractors.
3. IMPORTANT: Each distractor MUST have a CLEARLY DIFFERENT meaning from the correct answer. Do NOT use synonyms or near-synonyms — if a student argues "that also means the same thing", it's a BAD distractor.
4. Distractor strategies (use a MIX):
   - Related but WRONG: words from the same category/topic but meaning something completely different (e.g., for "slow down" = "减速", use "加速" (speed up), "停下来" (stop), "转弯" (turn) — NOT "放慢速度" or "慢下来" which are synonyms)
   - Opposite meaning: antonyms or contrasting actions
   - Same word family confusion: words that share characters but mean different things (e.g., "发现" vs "发明" vs "发展")
   - Context trap: plausible in the same situation but different action (e.g., for "wake up": "睡着" (fall asleep) not "醒来" (wake up synonym))
5. BAD example for "slow down": ["减速", "放慢速度", "慢下来", "降低速度"] — ALL are synonyms, any could be correct!
6. GOOD example for "slow down": ["减速", "加速", "停下来", "转弯"] — each has a distinct meaning.
7. Correct answer position should be random (not always A).
8. Difficulty suitable for children.
9. Return ONLY a JSON array, no other text.
10. Format: [{{"index": 0, "question": "introduce", "options": ["介绍", "发现", "推荐", "隐藏"], "correct_index": 0}}]

Return JSON:"""
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.7
            )
            content = response.choices[0].message.content.strip()
            parsed = self._parse_json_array(content)
            
            questions = []
            for i, item in enumerate(items):
                llm_result = None
                for r in parsed:
                    if r.get("index") == i:
                        llm_result = r
                        break
                
                if llm_result and llm_result.get("options") and len(llm_result["options"]) == 4:
                    correct_idx = llm_result.get("correct_index", 0)
                    questions.append({
                        "type": "en2zh",
                        "source_item": item,
                        "question_text": item["text"],
                        "answer": llm_result["options"][correct_idx],
                        "options": llm_result["options"],
                        "correct_index": correct_idx,
                        "chinese_hint": None,
                    })
                else:
                    # Fallback: use correct translation + random distractors
                    questions.append(self._fallback_choice(item))
            
            return questions
            
        except Exception as e:
            print(f"[QuizEngine] Multiple-choice LLM error: {e}")
            return [self._fallback_choice(item) for item in items]
    
    def _fallback_choice(self, item: dict) -> dict:
        """Fallback: generate a simple multiple-choice with the correct translation."""
        correct = item.get("translation", "未知")
        # Generate simple distractors (these won't be great without LLM)
        distractors = ["未知含义", "其他意思", "近义词"]
        options = [correct] + distractors
        random.shuffle(options)
        correct_idx = options.index(correct)
        
        return {
            "type": "en2zh",
            "source_item": item,
            "question_text": item["text"],
            "answer": correct,
            "options": options,
            "correct_index": correct_idx,
            "chinese_hint": None,
        }
    
    def _parse_json_array(self, content: str) -> list:
        """Robust JSON array extraction from LLM response."""
        # Try direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # Try regex extraction
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        
        # Try stripping markdown code blocks
        cleaned = re.sub(r'```(?:json)?\s*', '', content).strip()
        cleaned = cleaned.rstrip('`').strip()
        match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        
        print(f"[QuizEngine] Failed to parse JSON from: {content[:200]}")
        return []
    
    def validate_answer(self, question: dict, user_answer) -> bool:
        """Validate user answer locally (no LLM call).
        
        For multi-blank zh2en: user_answer is a list of strings (one per blank).
        For single-blank zh2en: user_answer is a string.
        For en2zh (multiple choice): user_answer is the selected option text.
        """
        if not user_answer:
            return False
        
        if question["type"] == "en2zh":
            # Multiple choice: exact match to option text
            if isinstance(user_answer, str):
                return user_answer.strip() == question.get("answer", "").strip()
            return False
        else:
            # zh2en: check against answers array
            answers = question.get("answers", [])
            if not answers:
                # Fallback to old "answer" field
                correct = question.get("answer", "").strip()
                if isinstance(user_answer, str):
                    return user_answer.strip().lower() == correct.lower()
                return False
            
            if isinstance(user_answer, list):
                # Multi-blank: compare each blank
                if len(user_answer) != len(answers):
                    return False
                return all(
                    ua.strip().lower() == ca.strip().lower()
                    for ua, ca in zip(user_answer, answers)
                )
            elif isinstance(user_answer, str):
                # Single blank: direct comparison
                if len(answers) == 1:
                    return user_answer.strip().lower() == answers[0].strip().lower()
                # Multiple blanks but single string: try space-separated
                parts = user_answer.strip().split()
                if len(parts) == len(answers):
                    return all(
                        p.strip().lower() == ca.strip().lower()
                        for p, ca in zip(parts, answers)
                    )
                return False
            return False
    
    def record_result(self, question: dict, is_correct: bool, user_answer=""):
        """Record answer result and update quiz stats."""
        source = question.get("source_item", {})
        
        # Convert list answer to string for display
        display_answer = user_answer
        if isinstance(user_answer, list):
            display_answer = " / ".join(user_answer)
        
        self.session_results.append({
            "question": question,
            "is_correct": is_correct,
            "user_answer": display_answer,
        })
        
        # Update persistent stats
        word_text = source.get("text", "")
        group = source.get("group", "Default")
        self.exercise_manager.update_quiz_stats(word_text, group, is_correct)
    
    def save_results(self):
        """Persist quiz stats to words.json."""
        self.exercise_manager.save_data()
    
    def get_session_summary(self) -> dict:
        """Return summary of current quiz session."""
        total = len(self.session_results)
        correct = sum(1 for r in self.session_results if r["is_correct"])
        
        zh2en_total = sum(1 for r in self.session_results if r["question"]["type"] == "zh2en")
        zh2en_correct = sum(1 for r in self.session_results if r["question"]["type"] == "zh2en" and r["is_correct"])
        
        en2zh_total = sum(1 for r in self.session_results if r["question"]["type"] == "en2zh")
        en2zh_correct = sum(1 for r in self.session_results if r["question"]["type"] == "en2zh" and r["is_correct"])
        
        wrong_items = [r for r in self.session_results if not r["is_correct"]]
        
        return {
            "total": total,
            "correct": correct,
            "score_pct": (correct / total * 100) if total > 0 else 0,
            "zh2en_total": zh2en_total,
            "zh2en_correct": zh2en_correct,
            "en2zh_total": en2zh_total,
            "en2zh_correct": en2zh_correct,
            "wrong_items": wrong_items,
        }
    
    # ========== QUIZ BANK MANAGEMENT ==========
    
    def _banks_file_path(self) -> str:
        return get_user_data_path("quiz_banks.json")
    
    def _load_banks_file(self) -> dict:
        """Safely read quiz_banks.json. Returns {"banks": []} if not found or corrupt."""
        path = self._banks_file_path()
        if not os.path.exists(path):
            return {"banks": []}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict) or "banks" not in data:
                    return {"banks": []}
                return data
        except Exception as e:
            print(f"[QuizEngine] Failed to read quiz_banks.json: {e}")
            return {"banks": []}
    
    def _save_banks_file(self, data: dict):
        """Write quiz_banks.json atomically."""
        path = self._banks_file_path()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[QuizEngine] Failed to write quiz_banks.json: {e}")
    
    def get_all_banks(self) -> list:
        """Return all saved quiz banks, sorted by created_at descending."""
        data = self._load_banks_file()
        banks = data.get("banks", [])
        banks.sort(key=lambda b: b.get("created_at", ""), reverse=True)
        return banks
    
    def delete_bank(self, bank_id: str) -> bool:
        """Delete a quiz bank by ID. Returns True if found and deleted."""
        data = self._load_banks_file()
        original_len = len(data["banks"])
        data["banks"] = [b for b in data["banks"] if b.get("id") != bank_id]
        if len(data["banks"]) < original_len:
            self._save_banks_file(data)
            return True
        return False
    
    def rename_bank(self, bank_id: str, new_name: str) -> bool:
        """Rename a quiz bank. Returns True if found and renamed."""
        data = self._load_banks_file()
        for b in data.get("banks", []):
            if b.get("id") == bank_id:
                b["name"] = new_name
                self._save_banks_file(data)
                return True
        return False
    
    def get_bank_by_id(self, bank_id: str) -> dict:
        """Get a single bank by ID. Returns None if not found."""
        data = self._load_banks_file()
        for b in data.get("banks", []):
            if b.get("id") == bank_id:
                return b
        return None
    
    def find_questions_for_words(self, word_texts: list) -> list:
        """Find questions from all banks that match the given word texts.
        Returns a list of question dicts matching the words."""
        if not word_texts:
            return []
        
        word_set = set(w.lower().strip() for w in word_texts)
        data = self._load_banks_file()
        all_questions = []
        seen_words = set()  # Avoid duplicate questions for same word
        
        for bank in data.get("banks", []):
            for q in bank.get("questions", []):
                source_text = q.get("source_item", {}).get("text", "").lower().strip()
                if source_text in word_set and source_text not in seen_words:
                    all_questions.append(copy.deepcopy(q))
                    seen_words.add(source_text)
        
        random.shuffle(all_questions)
        return all_questions
    
    def generate_bank(self, groups, count: int, name: str = None):
        """Generate a quiz bank via LLM and save to file. Runs in background.
        
        Args:
            groups: Group name(s) to generate from.
            count: Number of questions.
            name: Optional bank name. Auto-generated if None.
        """
        self._generating_bank = True
        self.questions = []
        self.session_results = []
        self.current_index = 0
        self._bank_name = name
        self._bank_groups = groups if isinstance(groups, list) else [groups]
        
        # Reuse start_quiz logic for word selection and LLM batching
        # But we need to NOT emit questions_ready — use _generating_bank flag
        all_words = self.exercise_manager.exercises.get("words", [])
        group_words = [w for w in all_words if w.get('group', 'Default') in self._bank_groups]
        
        if not group_words:
            self._generating_bank = False
            self.bank_generation_error.emit("No words found in selected groups.")
            return
        
        actual_count = min(count, len(group_words))
        selected = random.sample(group_words, actual_count)
        
        # Assign question types
        random.shuffle(selected)
        half = actual_count // 2
        type_assignments = []
        for i, item in enumerate(selected):
            if i < half:
                type_assignments.append(("en2zh", item))
            else:
                type_assignments.append(("zh2en", item))
        random.shuffle(type_assignments)
        
        # Separate local vs LLM
        local_questions = []
        llm_zh2en_items = []
        llm_en2zh_items = []
        
        for qtype, item in type_assignments:
            text = item.get("text", "")
            if qtype == "zh2en" and " " not in text.strip():
                local_questions.append({
                    "type": "zh2en",
                    "source_item": item,
                    "question_text": item.get("translation", ""),
                    "answers": [text],
                    "options": None,
                    "correct_index": None,
                    "chinese_hint": None,
                })
            elif qtype == "zh2en":
                llm_zh2en_items.append(item)
            else:
                llm_en2zh_items.append(item)
        
        self.questions.extend(local_questions)
        
        total_llm = len(llm_zh2en_items) + len(llm_en2zh_items)
        self._pending_batches = 0
        self._local_count = len(local_questions)
        self._total_expected = actual_count
        
        if total_llm == 0:
            # All local, save immediately
            random.shuffle(self.questions)
            self._finish_bank_generation()
            return
        
        # Batch LLM items
        batches = []
        for i in range(0, len(llm_zh2en_items), self.BATCH_SIZE):
            batches.append(("zh2en", llm_zh2en_items[i:i + self.BATCH_SIZE]))
        for i in range(0, len(llm_en2zh_items), self.BATCH_SIZE):
            batches.append(("en2zh", llm_en2zh_items[i:i + self.BATCH_SIZE]))
        
        self._pending_batches = len(batches)
        self.bank_progress_update.emit(len(local_questions), actual_count)
        
        for qtype, batch_items in batches:
            t = threading.Thread(
                target=self._generate_batch,
                args=(qtype, batch_items),
                daemon=True
            )
            t.start()
    
    def _finish_bank_generation(self):
        """Save generated questions as a bank to file and emit done signal."""
        self._generating_bank = False
        
        # Generate bank ID and name
        now = datetime.now()
        bank_id = f"bank_{now.strftime('%Y%m%d_%H%M%S')}_{random.randint(0x100000, 0xFFFFFF):06x}"
        
        if not self._bank_name:
            groups_str = "+".join(self._bank_groups)
            self._bank_name = f"{groups_str} ({len(self.questions)}题)"
        
        bank = {
            "id": bank_id,
            "name": self._bank_name,
            "source_groups": self._bank_groups,
            "question_count": len(self.questions),
            "created_at": now.isoformat(),
            "questions": self.questions,
        }
        
        # Save to file
        data = self._load_banks_file()
        data["banks"].append(bank)
        self._save_banks_file(data)
        
        self.bank_generation_done.emit(bank)
    
    def start_quiz_from_bank(self, bank_id: str, count: int = 0):
        """Load a quiz bank and start the quiz. Optionally limit question count.
        
        Args:
            bank_id: The bank ID to load.
            count: Max number of questions. 0 = use all questions.
        """
        self.session_results = []
        self.current_index = 0
        
        data = self._load_banks_file()
        bank = None
        for b in data.get("banks", []):
            if b.get("id") == bank_id:
                bank = b
                break
        
        if not bank:
            self.generation_error.emit(f"Quiz bank not found: {bank_id}")
            return
        
        self.questions = copy.deepcopy(bank.get("questions", []))
        if not self.questions:
            self.generation_error.emit("Quiz bank is empty.")
            return
        
        random.shuffle(self.questions)
        
        # Limit to requested count if specified
        if count > 0 and count < len(self.questions):
            self.questions = self.questions[:count]
        
        self.questions_ready.emit(self.questions)
    
    def start_quiz_with_questions(self, questions: list):
        """Start a quiz with a pre-built list of questions (e.g., from mistake review)."""
        self.session_results = []
        self.current_index = 0
        self.questions = copy.deepcopy(questions)
        random.shuffle(self.questions)
        self.questions_ready.emit(self.questions)
