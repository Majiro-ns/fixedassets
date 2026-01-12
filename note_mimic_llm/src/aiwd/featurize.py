from __future__ import annotations
import re
import math
from typing import Dict, List, Tuple


SPLIT_RE = re.compile(r"[。．!?？！]+")
PUNCTS = set(",.、。!！?？;；:：")


def split_sentences(text: str) -> List[str]:
    parts = [s.strip() for s in SPLIT_RE.split(text) if s.strip()]
    return parts


def tokenize(text: str) -> List[str]:
    try:
        from janome.tokenizer import Tokenizer  # type: ignore
        t = Tokenizer()
        return [tok.surface for tok in t.tokenize(text)]
    except Exception:
        # Fallback: simple regex tokens (kanji/hiragana/katakana/latin/digits)
        return re.findall(r"[\w一-龠ぁ-ゔァ-ヴー々〆〤]+", text)


def normalized_avg_sentence_len(sentences: List[str]) -> float:
    if not sentences:
        return 0.0
    lens = [len(s) for s in sentences if s]
    if not lens:
        return 0.0
    avg = sum(lens) / len(lens)
    # map 20 -> 0, 80 -> 1, clamp
    v = (avg - 20) / (80 - 20)
    return max(0.0, min(1.0, v))


DEFAULT_CONNECTIVES = [
    "また", "さらに", "一方で", "まず", "次に", "したがって", "つまり", "一方", "総じて",
    "結論として", "しかし", "ただし", "加えて"
]


def connective_rate(text: str, sentences: List[str], connectives: List[str] | None = None) -> float:
    connectives = connectives or DEFAULT_CONNECTIVES
    if not sentences:
        return 0.0
    heads = 0
    for s in sentences:
        s2 = s.strip()
        if any(s2.startswith(c) for c in connectives):
            heads += 1
    return heads / max(1, len(sentences))


def trigram_repeat_ratio(tokens: List[str]) -> float:
    # character-level trigrams may be more sensitive; using token trigrams for stability
    if len(tokens) < 3:
        return 0.0
    trigrams = []
    for i in range(len(tokens)-2):
        trigrams.append((tokens[i], tokens[i+1], tokens[i+2]))
    total = len(trigrams)
    unique = len(set(trigrams))
    if total == 0:
        return 0.0
    return (total - unique) / total


def rhythm_variance(text: str) -> float:
    # compute variance of distance between punctuations; lower variance => more AI-like
    idxs = [i for i, ch in enumerate(text) if ch in PUNCTS]
    if len(idxs) < 3:
        return 0.0
    gaps = [j - i for i, j in zip(idxs, idxs[1:]) if j > i]
    if not gaps:
        return 0.0
    mean = sum(gaps) / len(gaps)
    var = sum((g - mean)**2 for g in gaps) / len(gaps)
    # normalize: 1 - clamp(var / 200)
    score = 1.0 - min(1.0, var / 200.0)
    return max(0.0, min(1.0, score))


DEFAULT_ABSTRACT = [
    "重要", "影響", "観点", "側面", "要因", "可能性", "課題", "目的", "改善", "効果",
    "戦略", "一般的", "総合的", "包括的", "適切", "適合", "有効", "最適"
]


def abstract_rate(tokens: List[str], abstract_words: List[str] | None = None) -> float:
    abstract_words = abstract_words or DEFAULT_ABSTRACT
    if not tokens:
        return 0.0
    count = 0
    aset = set(abstract_words)
    for t in tokens:
        if t in aset:
            count += 1
    return count / max(1, len(tokens))


def punctuation_density(text: str) -> float:
    if not text:
        return 0.0
    c = sum(1 for ch in text if ch in PUNCTS)
    return c / max(1, len(text))


def ttr_ai(tokens: List[str]) -> float:
    if not tokens:
        return 0.0
    ttr = len(set(tokens)) / max(1, len(tokens))
    return 1.0 - ttr


def compute_features(text: str, connectives: List[str] | None = None, abstract_words: List[str] | None = None) -> Dict[str, float]:
    sentences = split_sentences(text)
    tokens = tokenize(text)
    feats = {
        "ttr_ai": ttr_ai(tokens),
        "avg_sentence_len": normalized_avg_sentence_len(sentences),
        "connective_rate": connective_rate(text, sentences, connectives),
        "trigram_repeat_ratio": trigram_repeat_ratio(tokens),
        "rhythm_variance": rhythm_variance(text),
        "abstract_rate": abstract_rate(tokens, abstract_words),
        "punct_density": punctuation_density(text),
        "length_chars": float(len(text)),
    }
    return feats

