import pytest

from ghostcrt.vault.snippets import (
    MAX_TEXT_LEN,
    SLOTS,
    Snippet,
    expand_snippet,
    normalize_snippet_name,
    snippet_keystrokes,
    snippet_text_error,
)


def test_slots_are_one_to_five():
    assert list(SLOTS) == [1, 2, 3, 4, 5]


@pytest.mark.parametrize(
    ("stored", "expanded"),
    [
        ("pw\\n", "pw\n"),  # \n escape
        ("a\\\\nb", "a\\nb"),  # \\ then n: a literal backslash-n
        ("a\\\\\\\\b", "a\\\\b"),  # two escaped backslashes
        ("line1\nline2", "line1\nline2"),  # real newline from the text box
        ("C:\\temp", "C:\\temp"),  # other backslashes are kept
        ("end\\", "end\\"),  # trailing backslash is kept
        ("tab\there", "tab\there"),
    ],
)
def test_expand_snippet(stored, expanded):
    assert expand_snippet(stored) == expanded


@pytest.mark.parametrize(
    ("stored", "sent"),
    [
        ("pw\\n", b"pw\r"),
        ("a\nb", b"a\rb"),
        ("a\r\nb", b"a\rb"),
        ("a\rb", b"a\rb"),
        ("a\\nb\\n", b"a\rb\r"),
        ("a\tb", b"a\tb"),
        ("şifre\\n", "şifre\r".encode()),
    ],
)
def test_snippet_keystrokes_end_lines_with_enter(stored, sent):
    assert snippet_keystrokes(stored) == sent


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("sudo", "sudo"),
        ("  sudo  ", "sudo"),
        ("x" * 16, "x" * 16),
        ("[b]x", "[b]x"),
        ("", None),
        ("   ", None),
        ("x" * 17, None),
        ("a\x01", None),
        ("a\x7f", None),
        ("a\nb", None),
    ],
)
def test_normalize_snippet_name(raw, stored):
    assert normalize_snippet_name(raw) == stored


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("", "Text cannot be empty."),
        ("x" * (MAX_TEXT_LEN + 1), "Text is longer than 4096 characters."),
        ("a\x1b[31m", "Text contains control characters."),
        ("a\rb", "Text contains control characters."),
        ("a\x7f", "Text contains control characters."),
        ("x" * MAX_TEXT_LEN, None),
        ("a\n\tb", None),
        ("pw\\n", None),
    ],
)
def test_snippet_text_error(text, error):
    assert snippet_text_error(text) == error


def test_snippet_repr_omits_text():
    snippet = Snippet(1, "sudo", "synthetic-secret")

    assert "synthetic-secret" not in repr(snippet)
    assert "sudo" in repr(snippet)
