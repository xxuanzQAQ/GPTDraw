"""命令公共小工具：@ 目标解析与长文本切分。"""

from __future__ import annotations

from gsuid_core.models import Event


def normalize_uid(value: str) -> str:
    token = str(value or "").strip().lstrip("@")
    if ":" in token:
        token = token.rsplit(":", 1)[-1]
    return token.strip()


def target_ids(ev: Event) -> list[str]:
    ids: list[str] = []
    if ev.at:
        ids.append(normalize_uid(ev.at))
    for item in ev.at_list or []:
        ids.append(normalize_uid(item))
    for token in ev.text.replace("，", " ").replace(",", " ").split():
        cleaned = normalize_uid(token)
        if cleaned.isdigit():
            ids.append(cleaned)
    return list(dict.fromkeys(uid for uid in ids if uid))


def split_text(text: str, limit: int = 1500) -> list[str]:
    if len(text) <= limit:
        return [text]
    return [text[start : start + limit] for start in range(0, len(text), limit)]


__all__ = ["normalize_uid", "split_text", "target_ids"]
