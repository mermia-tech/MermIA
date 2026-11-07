"""Text from an uploaded file is untrusted: clean it before it is stored or shown.

A file can carry control characters, bidi overrides that reorder what the manager reads, or a
value megabytes long. `clean` drops the first two and caps the length; `shown` is the short form
for echoing a bad value back in a refusal (both the Spanish message and the log detail).
"""

from __future__ import annotations

import unicodedata

ECHO_CHARS = 40  # how much of a bad value a refusal repeats
ELLIPSIS = "…"
# Cc: control characters (tab and newline become spaces); Zl, Zp: line and paragraph separators.
_AS_SPACE = frozenset(("Cc", "Zl", "Zp"))
# Cf: format characters, among them the bidi marks, embeddings, overrides and isolates and the
# zero-width characters. Dropped without a trace.
_DROPPED = frozenset(("Cf",))


def _visible(char: str) -> str:
    category = unicodedata.category(char)
    if category in _DROPPED:
        return ""
    return " " if category in _AS_SPACE else char


def clean(text: str, limit: int) -> str:
    """`text` without control, format or separator characters, its runs of whitespace collapsed
    to one space, and at most `limit` characters long (cut with an ellipsis)."""
    visible = " ".join("".join(map(_visible, text)).split())
    if len(visible) <= limit:
        return visible
    return visible[: limit - 1] + ELLIPSIS


def shown(raw: str) -> str:
    """A bad value as a refusal may repeat it: cleaned and at most ECHO_CHARS long."""
    return clean(raw[: ECHO_CHARS * 4], ECHO_CHARS)
