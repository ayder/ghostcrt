"""Snippet slots: the rules a stored snippet obeys and the keystrokes it types."""

from __future__ import annotations

from dataclasses import dataclass, field

SLOTS = range(1, 6)
MAX_NAME_LEN = 16
MAX_TEXT_LEN = 4096
_TEXT_CONTROLS = frozenset("\n\t")


@dataclass(frozen=True)
class Snippet:
    slot: int
    name: str
    # Snippets may hold passwords; keep the text out of reprs and tracebacks.
    text: str = field(repr=False)


def _has_control(value: str, allowed: frozenset[str] = frozenset()) -> bool:
    return any((ord(c) < 32 or ord(c) == 127) and c not in allowed for c in value)


def normalize_snippet_name(raw: str) -> str | None:
    """The stored form of a snippet name, or None when it breaks the rule."""
    candidate = raw.strip()
    if not 1 <= len(candidate) <= MAX_NAME_LEN or _has_control(candidate):
        return None
    return candidate


def snippet_text_error(text: str) -> str | None:
    """Why `text` cannot be stored, or None when it can."""
    if not text:
        return "Text cannot be empty."
    if len(text) > MAX_TEXT_LEN:
        return f"Text is longer than {MAX_TEXT_LEN} characters."
    if _has_control(text, _TEXT_CONTROLS):
        return "Text contains control characters."
    return None


def expand_snippet(text: str) -> str:
    r"""Resolve `\n` to a newline and `\\` to a backslash; keep any other backslash."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and text[i + 1 : i + 2] in ("n", "\\"):
            out.append("\n" if text[i + 1] == "n" else "\\")
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def snippet_keystrokes(text: str) -> bytes:
    """The bytes that type `text`: every line break is an Enter press (CR)."""
    expanded = expand_snippet(text).replace("\r\n", "\n").replace("\r", "\n")
    return expanded.replace("\n", "\r").encode("utf-8")
