"""
OralTestEngine - LLM-based oral test sentence generation and bank management.
Generates sentences containing vocabulary words for reading-aloud practice.
"""
import json
import os
import random
import threading
import uuid
from datetime import datetime

from src.core.qt_compat import QObject, pyqtSignal

from src.core.content_parser import _get_llm_client_and_model
from src.utils import get_user_data_path


class OralTestEngine(QObject):
    """Generates and manages oral reading test sentences."""

    # Signals
    sentences_ready = pyqtSignal(list)           # Emitted when sentences are generated
    generation_error = pyqtSignal(str)           # Emitted on error
    progress_update = pyqtSignal(int, int)       # (generated, total)

    # Bank signals
    bank_progress_update = pyqtSignal(int, int)  # (generated, total)
    bank_generation_done = pyqtSignal(dict)      # Full bank dict
    bank_generation_error = pyqtSignal(str)      # Error message

    BATCH_SIZE = 5  # Words per LLM call

    def __init__(self, exercise_manager):
        super().__init__()
        self.exercise_manager = exercise_manager
        self.sentences = []
        self._generating_bank = False

    # ------------------------------------------------------------------ #
    #  Sentence Generation                                                 #
    # ------------------------------------------------------------------ #
    def generate_sentences(self, groups, count: int, for_bank: bool = False):
        """
        Generate sentences for oral reading test.

        For each selected word, LLM creates a natural sentence containing it.
        Sentences from the 'sentences' category in the database are used directly.

        Args:
            groups: List of group names to draw words from.
            count: Total number of sentences to generate.
            for_bank: If True, emits bank signals instead of quiz signals.
        """
        self.sentences = []
        self._generating_bank = for_bank

        if isinstance(groups, str):
            groups = [groups]

        # Collect words and existing sentences from selected groups (incl. memorize days)
        from src.server.deps import get_all_practice_items
        all_items = get_all_practice_items(groups)
        group_words = [w for w in all_items if w.get("group", "Default") in groups]
        all_sentences = self.exercise_manager.exercises.get("sentences", [])
        group_sentences = [s for s in all_sentences if s.get('group', 'Default') in groups]

        if not group_words and not group_sentences:
            self._emit_error("所选分组中没有找到单词或句子。")
            return

        actual_count = min(count, len(group_words) + len(group_sentences))

        # Build pool: words (need LLM generation) + sentences (use directly)
        word_pool = list(group_words)
        sentence_pool = list(group_sentences)

        random.shuffle(word_pool)
        random.shuffle(sentence_pool)

        # Decide split: how many from words vs sentences
        # Prioritize sentences (they're already complete), fill rest with words
        n_sentences = min(len(sentence_pool), actual_count // 3)  # Up to 1/3 from existing sentences
        n_words = actual_count - n_sentences

        selected_words = word_pool[:n_words]
        selected_sentences = sentence_pool[:n_sentences]

        # Add existing sentences directly (they already have text + translation)
        for s in selected_sentences:
            self.sentences.append({
                "type": "existing",
                "text": s.get("text", ""),
                "translation": s.get("translation", ""),
                "source_word": s.get("text", ""),
                "source_group": s.get("group", "Default"),
            })

        if not selected_words:
            # No words to generate, all from existing sentences
            random.shuffle(self.sentences)
            self._emit_done()
            return

        # Batch LLM calls for word sentence generation
        batches = []
        for i in range(0, len(selected_words), self.BATCH_SIZE):
            batches.append(selected_words[i:i + self.BATCH_SIZE])

        self._pending_batches = len(batches)
        self._total_expected = actual_count

        progress_sig = self.bank_progress_update if for_bank else self.progress_update
        progress_sig.emit(len(self.sentences), actual_count)

        for batch in batches:
            t = threading.Thread(
                target=self._generate_batch,
                args=(batch,),
                daemon=True
            )
            t.start()

    def _generate_batch(self, items: list):
        """Generate sentences for a batch of words via LLM."""
        try:
            config_path = get_user_data_path("config.json")
            config = {}
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            client, model = _get_llm_client_and_model(config)
            new_sentences = self._call_llm_for_sentences(client, model, items)
            self.sentences.extend(new_sentences)

        except Exception as e:
            print(f"[OralTestEngine] Batch error: {e}")
            # Fallback: use word itself as the sentence
            for item in items:
                self.sentences.append({
                    "type": "fallback",
                    "text": item.get("text", ""),
                    "translation": item.get("translation", ""),
                    "source_word": item.get("text", ""),
                    "source_group": item.get("group", "Default"),
                })
        finally:
            self._pending_batches -= 1
            progress_sig = self.bank_progress_update if self._generating_bank else self.progress_update
            progress_sig.emit(len(self.sentences), self._total_expected)

            if self._pending_batches <= 0:
                random.shuffle(self.sentences)
                self._emit_done()

    def _call_llm_for_sentences(self, client, model: str, items: list) -> list:
        """Call LLM to generate natural sentences containing each word."""
        item_list = "\n".join([
            f'{i+1}. "{item["text"]}" (中文: {item.get("translation", "N/A")})'
            for i, item in enumerate(items)
        ])

        prompt = f"""You are an English teacher creating oral reading practice for Chinese children (age 8-12).

For each vocabulary word below, generate ONE natural, simple English sentence that CONTAINS the word.

Words:
{item_list}

Rules:
1. The sentence must naturally include the exact word (do not change its form for nouns/verbs unless grammatically necessary).
2. Keep sentences short (6-12 words), suitable for children to read aloud.
3. Use common vocabulary and simple grammar.
4. Provide a natural Chinese translation of the FULL sentence.
5. Mark the target word in the sentence with **bold** (surround with **).
6. Return ONLY a JSON array, no other text.

Format:
[{{"index": 0, "sentence": "Let me **introduce** my best friend to you.", "translation": "让我把我最好的朋友介绍给你。", "target_word": "introduce"}}]

Return JSON:"""

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.4
        )
        content = response.choices[0].message.content.strip()
        parsed = self._parse_json_array(content)

        results = []
        for i, item in enumerate(items):
            llm_result = None
            for r in parsed:
                if r.get("index") == i:
                    llm_result = r
                    break

            if llm_result and llm_result.get("sentence"):
                # Remove ** bold markers for the reading text
                sentence = llm_result["sentence"].replace("**", "").strip()
                translation = llm_result.get("translation", item.get("translation", ""))
                results.append({
                    "type": "generated",
                    "text": sentence,
                    "translation": translation,
                    "source_word": item.get("text", ""),
                    "source_group": item.get("group", "Default"),
                    "target_word": llm_result.get("target_word", item.get("text", "")),
                })
            else:
                # Fallback: use the word directly
                results.append({
                    "type": "fallback",
                    "text": item.get("text", ""),
                    "translation": item.get("translation", ""),
                    "source_word": item.get("text", ""),
                    "source_group": item.get("group", "Default"),
                })

        return results

    # ------------------------------------------------------------------ #
    #  Bank Management (mirrors QuizEngine bank logic)                    #
    # ------------------------------------------------------------------ #
    def _banks_file_path(self) -> str:
        return get_user_data_path("oral_test_banks.json")

    def _load_banks_file(self) -> dict:
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
            print(f"[OralTestEngine] Failed to read oral_test_banks.json: {e}")
            return {"banks": []}

    def _save_banks_file(self, data: dict):
        path = self._banks_file_path()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[OralTestEngine] Failed to write oral_test_banks.json: {e}")

    def get_all_banks(self) -> list:
        data = self._load_banks_file()
        banks = data.get("banks", [])
        banks.sort(key=lambda b: b.get("created_at", ""), reverse=True)
        return banks

    def delete_bank(self, bank_id: str) -> bool:
        data = self._load_banks_file()
        original_len = len(data["banks"])
        data["banks"] = [b for b in data["banks"] if b.get("id") != bank_id]
        if len(data["banks"]) < original_len:
            self._save_banks_file(data)
            return True
        return False

    def rename_bank(self, bank_id: str, new_name: str) -> bool:
        data = self._load_banks_file()
        for b in data.get("banks", []):
            if b.get("id") == bank_id:
                b["name"] = new_name
                self._save_banks_file(data)
                return True
        return False

    def get_bank_by_id(self, bank_id: str) -> dict:
        data = self._load_banks_file()
        for b in data.get("banks", []):
            if b.get("id") == bank_id:
                return b
        return None

    def generate_bank(self, groups, count: int):
        """Generate a persistent oral test bank and save to file."""
        self._generating_bank = True
        self._bank_groups = groups
        self._bank_count = count

        # Connect to internal completion handler
        self._bank_done_handler = self._finish_bank_generation
        self.generate_sentences(groups, count, for_bank=True)

    def _finish_bank_generation(self):
        """Save generated sentences as a new bank."""
        if not self.sentences:
            self.bank_generation_error.emit("生成失败：没有成功生成任何句子。")
            return

        bank_id = str(uuid.uuid4())[:8]
        groups = self._bank_groups if hasattr(self, '_bank_groups') else []

        # Build a readable name
        group_str = "+".join(groups[:3])
        if len(groups) > 3:
            group_str += f"+{len(groups)-3}more"
        name = f"口语测试_{group_str}_{len(self.sentences)}句"

        bank = {
            "id": bank_id,
            "name": name,
            "source_groups": groups,
            "sentence_count": len(self.sentences),
            "created_at": datetime.now().isoformat(),
            "sentences": self.sentences,
        }

        data = self._load_banks_file()
        data["banks"].append(bank)
        self._save_banks_file(data)

        self._generating_bank = False
        self.bank_generation_done.emit(bank)

    def load_bank_sentences(self, bank_id: str) -> list:
        """Load sentences from a bank for practice."""
        bank = self.get_bank_by_id(bank_id)
        if not bank:
            return []
        return bank.get("sentences", [])

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #
    def _parse_json_array(self, content: str) -> list:
        """Parse JSON array from LLM response, handling markdown fences."""
        import re
        # Strip markdown code blocks
        content = re.sub(r'```(?:json)?\s*', '', content)
        content = re.sub(r'```\s*$', '', content)
        content = content.strip()

        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # Try to find array in the content
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return []

    def _emit_error(self, msg: str):
        if self._generating_bank:
            self.bank_generation_error.emit(msg)
        else:
            self.generation_error.emit(msg)

    def _emit_done(self):
        if self._generating_bank:
            self._finish_bank_generation()
        else:
            self.sentences_ready.emit(self.sentences)
