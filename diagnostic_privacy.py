"""Conservative filtering of obvious access data in copied log excerpts.

This is a best-effort sharing filter, not a guarantee for arbitrary log text.
Never alter the original local log: filtering belongs only to the export path.
"""

import re


_ADDRESS = re.compile(r"[a-z][a-z0-9+.-]*://", re.I)
_SECRET = re.compile(
    r"\b(?:password|passwd|username|user|token|access_token|refresh_token|"
    r"authorization|proxy-authorization|cookie|set-cookie|secret|api[-_]key|mac)"
    r"[\"']?\s*[:=]|\bbearer\s+\S+", re.I)


def sharing_excerpt(text):
    # Redact the whole line, not only a guessed URL fragment. Quotes, spaces,
    # encoded parameters and extra URLs may otherwise leave credential tails.
    return "\n".join("[***]" if _ADDRESS.search(line) or _SECRET.search(line) else line
                     for line in text.splitlines())
