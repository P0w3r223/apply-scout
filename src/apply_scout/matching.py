"""Crude text matching, shared by the guardrail and the eval harness.

This lived in `evaluation.py` while scoring was its only caller. The guardrail now needs
the same "does this text name that skill" test to check a report against the posting it
claims to describe — and a guardrail that imports from the harness would have the
dependency backwards: the harness scores what the guardrail produced, never the reverse.

Deliberately blunt, and kept that way on purpose: it exists to stop `embeddings` and
`embedding models` counting as different skills, not to do linguistics. Anything cleverer
would need its own tests to justify, and a rule nobody can re-derive by hand is worse
than a blunt one.
"""

from __future__ import annotations

import re


def tokens(text: str) -> list[str]:
    r"""Lowercased word tokens, with a trailing plural `s` folded away.

    Split on non-word characters with `\w` rather than an ASCII class, because two of the
    eight evaluation postings are Polish: `[^a-z0-9+#]` turned `różnych` into `['r', 'nych']`,
    so a one-letter needle like `R` matched the debris of an unrelated word. `+` and `#` stay
    in the word class for `C++` and `C#`.
    """
    words = re.split(r"[^\w+#]+", text.lower(), flags=re.UNICODE)
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w]


def mentions(haystack: str, needle: str) -> bool:
    """Whether `haystack` names what `needle` asks for.

    Containment, not equality: an annotation says `PyTorch` while a posting says
    "experience with PyTorch or TensorFlow in production". Those are the same finding,
    and scoring them as a miss measures the annotation format rather than the extraction.
    Tokens must appear consecutively, so `vector databases` does not match a text that
    merely happens to contain both words far apart.
    """
    want = tokens(needle)
    if not want:
        return False
    got = tokens(haystack)
    return any(got[i : i + len(want)] == want for i in range(len(got) - len(want) + 1))
