"""Bounded VOD bookmarks containing hashes and times, never stream addresses."""

import hashlib
import json
import re
import time

_KEY = re.compile(r"[0-9a-f]{64}\Z")
MAX_MS = 7 * 24 * 60 * 60 * 1000


def item_key(channel):
    if not isinstance(channel, dict) or channel.get("kind") != "movie" or not channel.get("url"):
        return ""
    identity = [str(channel.get(field) or "") for field in ("provider-id", "url")]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def normalize(entries):
    if not isinstance(entries, dict):
        return {}
    result = {}
    for key, value in entries.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key) or not isinstance(value, dict):
            continue
        position, length, updated = (value.get(name) for name in ("position_ms", "length_ms", "updated"))
        if not all(type(n) is int for n in (position, length, updated)):
            continue
        if not 30_000 <= position < length <= MAX_MS or not 0 <= updated <= 2**63 - 1:
            continue
        if length - position <= max(30_000, length // 20):
            continue
        result[key] = {"position_ms": position, "length_ms": length, "updated": updated}
    return dict(sorted(result.items(), key=lambda pair: pair[1]["updated"], reverse=True)[:200])


def checkpoint(entries, key, position, length, *, now=None):
    result = normalize(entries)
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        return result
    if type(position) is not int or type(length) is not int or not 0 <= position <= length <= MAX_MS:
        return result
    if length == 0:
        return result  # unknown duration is not proof of completion
    if position < 30_000 or length - position <= max(30_000, length // 20):
        result.pop(key, None)
    else:
        result[key] = {"position_ms": position, "length_ms": length,
                       "updated": int(time.time() if now is None else now)}
    return normalize(result)
