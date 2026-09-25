"""
GOP scorer: TopK GOP, sigmoid mapping, aggregation, error classification.

Algorithm:
  GOP(p) = log P(target_p | frames) - logsumexp(top5 competitors except target | frames)
  score(p) = sigmoid_map(GOP(p))

Aggregation:
  word_score   = frame-weighted mean of phoneme scores (low-confidence ones excluded)
  overall      = sum(word_score * len) / sum(len)
  fluency      = 100 - sigma(phoneme_durations) * scale  (uniform durations -> high)
  completeness = matched / expected

Errors:
  substitution    : aligned token != argmax token at the segment, both phonemes mappable
  deletion        : alignment_confidence below gating threshold OR target_token_id == -1
  insertion       : extra ASR-decoded phoneme not present in expected sequence
  vowel_confusion : substitution where both expected and actual are ARPABET vowels
"""
from __future__ import annotations

import math
from typing import List, Tuple

from src.core.gop.schema import (
    PhonemeScore, WordScore, GopError, GopResult,
    PIPELINE_VERSION, is_vowel,
)
from src.core.gop.aligner import AlignmentResult, ARPABET_TO_IPA


# ---------------- Constants (calibrated for kids speech, can be tuned) ----------------
# 默认值（可通过 config.json 的 gop_calib 子字段覆盖）
SIGMOID_K = 1.5
SIGMOID_MID = -2.0
TOP_K = 5
ALIGNMENT_CONF_THRESHOLD = 0.30   # below this -> deletion, excluded from word avg
SUBSTITUTION_CONF_MIN = 0.50      # min argmax-token posterior to count as substitution
GOP_FLOOR = -2.0                  # GOP 保护阈值：低于此值时用 P_target 替代 GOP 对比
MIN_RELIABLE_DURATION = 0.04      # 音素最短可信时长(s)；短于此值视为对齐噪声，不计入 expected

# 聚合侧可调参数（aggregate 函数用）
CONF_EXPONENT = 1.2       # overall/completeness 的惩罚指数（1=线性，2=苛刻）
LOW_CONF_WEIGHT = 0.1     # 低置信音素对单词分的参与权重

# 默认配置模板（供 UI/保存时用）
DEFAULT_CALIB = {
    "sigmoid_k": SIGMOID_K,
    "sigmoid_mid": SIGMOID_MID,
    "conf_threshold": ALIGNMENT_CONF_THRESHOLD,
    "substitution_conf_min": SUBSTITUTION_CONF_MIN,
    "conf_exponent": CONF_EXPONENT,
    "low_conf_weight": LOW_CONF_WEIGHT,
    "gop_floor": GOP_FLOOR,
    "min_reliable_duration": MIN_RELIABLE_DURATION,
}


def update_calib(calib: dict) -> None:
    """Apply config overrides to module-level tuning constants.

    典型字段：sigmoid_k / sigmoid_mid / conf_threshold /
              substitution_conf_min / conf_exponent / low_conf_weight / gop_floor。
    只覆盖显式传入的键，其余保留上次值。
    """
    global SIGMOID_K, SIGMOID_MID, ALIGNMENT_CONF_THRESHOLD
    global SUBSTITUTION_CONF_MIN, CONF_EXPONENT, LOW_CONF_WEIGHT, GOP_FLOOR
    global MIN_RELIABLE_DURATION
    if not isinstance(calib, dict):
        return
    if "sigmoid_k" in calib:
        SIGMOID_K = float(calib["sigmoid_k"])
    if "sigmoid_mid" in calib:
        SIGMOID_MID = float(calib["sigmoid_mid"])
    if "conf_threshold" in calib:
        ALIGNMENT_CONF_THRESHOLD = float(calib["conf_threshold"])
    if "substitution_conf_min" in calib:
        SUBSTITUTION_CONF_MIN = float(calib["substitution_conf_min"])
    if "conf_exponent" in calib:
        CONF_EXPONENT = float(calib["conf_exponent"])
    if "low_conf_weight" in calib:
        LOW_CONF_WEIGHT = float(calib["low_conf_weight"])
    if "gop_floor" in calib:
        GOP_FLOOR = float(calib["gop_floor"])
    if "min_reliable_duration" in calib:
        MIN_RELIABLE_DURATION = float(calib["min_reliable_duration"])


def load_calib_from_config() -> None:
    """Read config.json -> gop_calib sub-dict and apply it.

    Silently ignores missing / unreadable config (keeps defaults).
    """
    try:
        from src.utils import get_user_data_path
        import json as _json, os as _os
        path = get_user_data_path("config.json")
        if not path or not _os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            cfg = _json.load(f)
        calib = cfg.get("gop_calib") or {}
        update_calib(calib)
    except Exception as e:
        print(f"[gop.scorer] load_calib_from_config failed: {e}")


def sigmoid_score(gop: float, k: float = None, mid: float = None) -> int:
    """Map raw GOP to [0, 100]. Higher GOP -> higher score."""
    if k is None:
        k = SIGMOID_K
    if mid is None:
        mid = SIGMOID_MID
    try:
        x = k * (gop - mid)
        # Clip to avoid overflow.
        if x > 30:
            return 100
        if x < -30:
            return 0
        s = 100.0 / (1.0 + math.exp(-x))
        return max(0, min(100, int(round(s))))
    except Exception:
        return 0


def hybrid_score(gop: float, target_prob: float, k: float = None, mid: float = None,
                 gop_floor: float = None) -> int:
    """Blend GOP-sigmoid score with target posterior when GOP is very negative.

    原理：GOP 算法在模型对整段音频不确定（儿童音色/环境噪声/非标准口音）时
    会系统性压低分数。此时目标音素自身的后验概率 P(target) 是更鲁棒的信号。
    当 GOP < gop_floor 时，用 P(target)*100 平滑替代 sigmoid(GOP)。

    返回：0-100 整数。
    """
    base = sigmoid_score(gop, k=k, mid=mid)
    if gop_floor is None:
        gop_floor = GOP_FLOOR
    if gop >= gop_floor:
        return base
    # 距离 floor 越远，越依赖 P_target
    gap = gop_floor - gop
    w = min(1.0, gap / 5.0)
    p_score = max(0.0, min(100.0, target_prob * 100.0))
    blended = (1.0 - w) * base + w * p_score
    return max(0, min(100, int(round(blended))))


def _topk_competitor_logsumexp(log_probs_row, target_id: int, blank_id: int, k: int = TOP_K) -> float:
    """logsumexp over top-K competitors (excluding target and blank)."""
    import torch
    row = log_probs_row.clone()
    if target_id >= 0:
        row[target_id] = float("-1e30")
    row[blank_id] = float("-1e30")
    if row.numel() == 0:
        return float("-1e30")
    k_eff = min(k, row.numel())
    top_vals, _ = torch.topk(row, k=k_eff)
    return float(torch.logsumexp(top_vals, dim=0).item())


def _argmax_phoneme_at(log_probs, start: int, end: int, blank_id: int, id_to_token: dict) -> Tuple[str, float]:
    """Return (token_str, posterior) of argmax non-blank token across a frame range."""
    import torch
    if end <= start:
        end = start + 1
    sub = log_probs[start:end].clone()
    sub[:, blank_id] = float("-1e30")
    # frame-mean log probs over the segment, then argmax.
    mean_lp = sub.mean(dim=0)
    best_id = int(torch.argmax(mean_lp).item())
    posterior = float(torch.exp(mean_lp[best_id]).item())
    tok = id_to_token.get(best_id, "")
    return tok, posterior


def _ipa_to_arpabet(ipa_token: str) -> str:
    """Reverse-lookup an ARPABET symbol from an IPA token (best-effort)."""
    if not ipa_token:
        return ""
    # Build reverse table once (cached on function attribute).
    cache = getattr(_ipa_to_arpabet, "_cache", None)
    if cache is None:
        cache = {}
        for arp, ipa in ARPABET_TO_IPA.items():
            if ipa and ipa not in cache:
                cache[ipa] = arp
            if ipa and len(ipa) == 1:
                cache[ipa.lower()] = arp
        _ipa_to_arpabet._cache = cache
    return cache.get(ipa_token, ipa_token.upper())


def compute_phoneme_scores(
    align_result: AlignmentResult,
    id_to_token: dict,
) -> List[PhonemeScore]:
    """Per-phoneme TopK GOP score + alignment confidence gating."""
    out: List[PhonemeScore] = []
    log_probs = align_result.log_probs
    frame_dur = align_result.frame_duration_s
    blank_id = align_result.blank_token_id

    for i, ph in enumerate(align_result.alignment):
        tid = align_result.target_token_ids[i]
        st, en = ph.start_frame, ph.end_frame
        if en <= st:
            en = st + 1

        if tid >= 0 and tid < log_probs.shape[1]:
            # Mean log P(target | frames over segment).
            target_lp = float(log_probs[st:en, tid].mean().item())
            # TopK competitors, computed on segment-mean log probs.
            seg_mean = log_probs[st:en].mean(dim=0)
            competitor_lse = _topk_competitor_logsumexp(seg_mean, tid, blank_id, k=TOP_K)
            gop = target_lp - competitor_lse
            # P(target)：目标音素的后验概率（hybrid_score 在 GOP 过低时用作保底）
            target_prob = math.exp(target_lp)
            score = hybrid_score(
                gop, target_prob,
                k=SIGMOID_K, mid=SIGMOID_MID, gop_floor=GOP_FLOOR,
            )
        else:
            # Target not in vocab -> can't compute GOP; treat as deletion candidate.
            gop = float("-inf")
            score = 0

        low_conf = (ph.confidence < ALIGNMENT_CONF_THRESHOLD) or (tid < 0)
        if low_conf:
            # 动态 cap：confidence 越高，允许的分数上限越高
            # conf=0.0 -> cap=10；conf=0.15 -> cap=30；conf=0.29 -> cap=50
            dyn_cap = int(round(10 + ph.confidence * 140))
            dyn_cap = max(10, min(80, dyn_cap))
            score = min(score, dyn_cap)

        out.append(PhonemeScore(
            phoneme=ph.phoneme,
            score=score,
            start=round(st * frame_dur, 3),
            end=round(en * frame_dur, 3),
            alignment_confidence=round(float(ph.confidence), 3),
            low_confidence=low_conf,
        ))
    return out


def classify_errors(
    phoneme_scores: List[PhonemeScore],
    align_result: AlignmentResult,
    id_to_token: dict,
    word_for_phoneme_idx: List[str],
    word_local_pos: List[int],
) -> List[GopError]:
    """Return list of GopError per plan rules."""
    errors: List[GopError] = []
    log_probs = align_result.log_probs
    blank_id = align_result.blank_token_id

    expected_set = set()
    for i, ph in enumerate(phoneme_scores):
        expected_set.add(ph.phoneme)

    for i, ph in enumerate(phoneme_scores):
        tid = align_result.target_token_ids[i]
        st = align_result.alignment[i].start_frame
        en = align_result.alignment[i].end_frame
        word = word_for_phoneme_idx[i]
        local_pos = word_local_pos[i]
        duration = max(0.001, ph.end - ph.start)

        # 1. deletion: low confidence OR no vocab token
        if ph.low_confidence:
            # 微帧音素（对齐噪声）不报告为 deletion
            if duration >= MIN_RELIABLE_DURATION:
                errors.append(GopError(
                    type="deletion",
                    expected=ph.phoneme,
                    actual="",
                    word=word,
                    position=local_pos,
                ))
            continue

        # 2. substitution: argmax token at the segment != target token
        argmax_tok, argmax_post = _argmax_phoneme_at(log_probs, st, en, blank_id, id_to_token)
        target_tok = id_to_token.get(tid, "") if tid >= 0 else ""
        if (argmax_tok and target_tok and argmax_tok != target_tok
                and argmax_post >= SUBSTITUTION_CONF_MIN
                and ph.score < 70):
            actual_arp = _ipa_to_arpabet(argmax_tok)
            err_type = "vowel_confusion" if (is_vowel(ph.phoneme) and is_vowel(actual_arp)) else "substitution"
            errors.append(GopError(
                type=err_type,
                expected=ph.phoneme,
                actual=actual_arp,
                word=word,
                position=local_pos,
            ))

    # 3. insertion: ASR-decoded extra phonemes not in expected set.
    asr_tokens = [t for t in (align_result.asr_text or "").split() if t]
    seen_extra = set()
    for tok in asr_tokens:
        arp = _ipa_to_arpabet(tok)
        if not arp or arp in expected_set:
            continue
        if arp in seen_extra:
            continue
        seen_extra.add(arp)
        errors.append(GopError(
            type="insertion",
            expected="",
            actual=arp,
            word="",
            position=-1,
        ))
    return errors


def aggregate(
    phoneme_scores: List[PhonemeScore],
    word_phoneme_pairs: List[Tuple[str, List[str]]],
    align_result: AlignmentResult,
) -> Tuple[List[WordScore], int, int, int]:
    """Aggregate phoneme scores -> word + sentence + fluency + completeness.

    改进点（v3 - 防止"删除很多音素仍得 100 分"，同时不过度苛刻）：
    ① 单词得分：低置信音素按 0.1 权重纳入（保留对首字母/尾音删除的感知）。
    ② overall = base × (matched/expected)^1.2：温和二次惩罚。
    ③ completeness = base^1.2 - insertion_penalty。
    """
    words: List[WordScore] = []
    sentence_num = 0.0
    sentence_den = 0.0
    matched = 0
    expected = 0

    # 低置信音素权重：保留其对分数的部分贡献，避免完全排除造成虚高
    # （读取模块级可调全局：CONF_EXPONENT, LOW_CONF_WEIGHT, MIN_RELIABLE_DURATION）
    low_conf_weight = LOW_CONF_WEIGHT
    conf_exponent = CONF_EXPONENT
    min_dur = MIN_RELIABLE_DURATION

    idx = 0
    for word, phones in word_phoneme_pairs:
        word_phs: List[PhonemeScore] = []
        word_num = 0.0
        word_den = 0.0
        for _ in phones:
            ps = phoneme_scores[idx]
            word_phs.append(ps)
            duration = max(0.001, ps.end - ps.start)
            # 微帧音素（对齐噪声）不计入 expected/matched
            is_micro = (duration < min_dur) and ps.low_confidence
            if not is_micro:
                expected += 1
            if not ps.low_confidence:
                # 正常音素：全权重
                word_num += ps.score * duration
                word_den += duration
                if not is_micro:
                    matched += 1
            else:
                # 低置信音素：按 low_conf_weight 权重参与
                word_num += ps.score * duration * low_conf_weight
                word_den += duration * low_conf_weight
            idx += 1
        if word_den > 0:
            wscore = int(round(word_num / word_den))
        else:
            wscore = 0
        wscore = max(0, min(100, wscore))

        words.append(WordScore(word=word, score=wscore, phonemes=word_phs))

        # Sentence aggregation: weight word by total expected phoneme duration.
        word_dur_total = sum(max(0.001, p.end - p.start) for p in word_phs)
        sentence_num += wscore * max(word_dur_total, 0.001)
        sentence_den += max(word_dur_total, 0.001)

    base_overall = int(round(sentence_num / sentence_den)) if sentence_den > 0 else 0
    base_overall = max(0, min(100, base_overall))

    # ② overall 温和惩罚：conf_ratio^conf_exponent
    conf_ratio = (matched / expected) if expected > 0 else 1.0
    overall = int(round(base_overall * (conf_ratio ** conf_exponent)))
    overall = max(0, min(100, overall))

    # Fluency: lower duration variance -> higher fluency.
    durations = [max(0.001, p.end - p.start) for p in phoneme_scores if not p.low_confidence]
    if len(durations) >= 2:
        mean = sum(durations) / len(durations)
        var = sum((d - mean) ** 2 for d in durations) / len(durations)
        std = math.sqrt(var)
        cv = std / mean if mean > 0 else 1.0
        # cv ~ 0 -> 100, cv >= 1 -> ~30. Map with a soft curve.
        fluency = max(20, min(100, int(round(100.0 - cv * 70.0))))
    else:
        fluency = 60

    # ③ completeness 同样温和惩罚 + insertion 扣分
    insertions = sum(1 for tok in (align_result.asr_text or "").split() if tok
                     and _ipa_to_arpabet(tok) not in
                     {ps.phoneme for ps in phoneme_scores})
    raw_comp = int(round((conf_ratio ** conf_exponent) * 100))
    ins_penalty = min(raw_comp, max(0, insertions))  # 每个插入扣 1 分
    completeness = max(0, raw_comp - ins_penalty)
    completeness = max(0, min(100, completeness))

    return words, overall, fluency, completeness


def score_alignment(
    reference_text: str,
    align_result: AlignmentResult,
    id_to_token: dict,
    word_phoneme_pairs: List[Tuple[str, List[str]]],
    fingerprint: str,
    elapsed_ms: int,
) -> GopResult:
    """Top-level: alignment -> phoneme scores -> aggregation -> errors -> GopResult."""
    phoneme_scores = compute_phoneme_scores(align_result, id_to_token)

    # Build word-attribution arrays for error classification.
    word_for_phoneme_idx: List[str] = []
    word_local_pos: List[int] = []
    for word, phones in word_phoneme_pairs:
        for j, _ in enumerate(phones):
            word_for_phoneme_idx.append(word)
            word_local_pos.append(j)

    words, overall, fluency, completeness = aggregate(
        phoneme_scores, word_phoneme_pairs, align_result
    )
    errors = classify_errors(
        phoneme_scores, align_result, id_to_token,
        word_for_phoneme_idx, word_local_pos,
    )

    return GopResult(
        text=reference_text,
        asr_text=align_result.asr_text,
        words=words,
        errors=errors,
        overall_score=overall,
        fluency_score=fluency,
        completeness_score=completeness,
        model_fingerprint=fingerprint,
        pipeline_version=PIPELINE_VERSION,
        elapsed_ms=elapsed_ms,
    )
