from __future__ import annotations
from typing import Tuple, List


def _chunks(s: str, max_len: int = 700) -> List[str]:
    out = []
    cur = []
    length = 0
    for ch in s:
        cur.append(ch)
        length += 1
        if length >= max_len:
            out.append("".join(cur))
            cur = []
            length = 0
    if cur:
        out.append("".join(cur))
    return out


def try_hf_probs(text: str, model_id: str = "Hello-SimpleAI/chatgpt-detector-roberta", max_chunks: int = 40) -> Tuple[float | None, float | None, str | None]:
    try:
        from transformers import pipeline  # type: ignore
    except Exception as e:
        return None, None, f"transformersが使用できません: {e}"

    try:
        nlp = pipeline("text-classification", model=model_id, tokenizer=model_id, return_all_scores=True)
        chunks = _chunks(text, 700)[:max_chunks]
        if not chunks:
            return 0.0, 0.0, None
        probs = []
        for c in chunks:
            scores = nlp(c)[0]
            # Map labels to AI-likeness probability
            p_ai = None
            for s in scores:
                label = str(s.get("label", "")).lower()
                score = float(s.get("score", 0.0))
                if "ai" in label:
                    p_ai = score
                    break
            if p_ai is None:
                # fallback if only HUMAN present
                human = None
                for s in scores:
                    if "human" in str(s.get("label", "")).lower():
                        human = float(s.get("score", 0.0))
                        break
                p_ai = 1.0 - (human if human is not None else 0.0)
            probs.append(p_ai)
        mean_p = sum(probs)/len(probs)
        max_p = max(probs)
        return mean_p, max_p, None
    except Exception as e:
        return None, None, f"HF推論に失敗: {e}"

