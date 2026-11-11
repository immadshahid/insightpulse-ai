"""Masking of personal data before anything is sent to the LLM.

* Emails and phone numbers are replaced by placeholders anywhere in text.
* Values in personal columns (names, emails, phones, addresses, CNIC) are redacted.
* Customer identifiers are pseudonymised ("Customer 1", "Customer 2", ...) and mapped
  back locally after the LLM answers, so real values never leave the server.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.pipeline.cleaner import is_pii_column

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Pakistani mobiles (03xx-xxxxxxx, +92 3xx xxxxxxx) and other long digit runs with
# separators that look like phone numbers.
PHONE_RE = re.compile(
    r"(?:\+?92[\s-]?|0)3\d{2}[\s-]?\d{7}\b|\+\d{1,3}[\s-]?\d{3,4}[\s-]?\d{3,4}" r"[\s-]?\d{3,4}\b"
)
CNIC_RE = re.compile(r"\b\d{5}-\d{7}-\d\b")


def mask_text(text: str) -> str:
    """Replace emails, phone numbers and CNICs in free text."""
    text = EMAIL_RE.sub("[email]", text)
    text = CNIC_RE.sub("[id-number]", text)
    return PHONE_RE.sub("[phone]", text)


def mask_sample_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Redact personal columns and mask emails/phones in the remaining sample values."""
    out = []
    for row in rows:
        masked = {}
        for col, value in row.items():
            if is_pii_column(col):
                masked[col] = "[redacted]" if value else ""
            else:
                masked[col] = mask_text(value)
        out.append(masked)
    return out


class Pseudonymizer:
    """Reversible mapping of real identifiers to neutral labels for one LLM exchange."""

    def __init__(self, prefix: str = "Customer") -> None:
        self.prefix = prefix
        self.forward: dict[str, str] = {}
        self.backward: dict[str, str] = {}

    def alias(self, value: Any) -> str:
        """Stable alias for ``value`` (creates one on first use)."""
        key = str(value)
        if key not in self.forward:
            label = f"{self.prefix} {len(self.forward) + 1}"
            self.forward[key] = label
            self.backward[label] = key
        return self.forward[key]

    def mask_known(self, text: str, known: Iterable[str]) -> str:
        """Replace any known identifier that appears in ``text`` with its alias.

        Aliases are numbered in order of first appearance; longer identifiers are
        replaced first so 'C10023' is never partly matched by 'C1002'.
        """
        found = {str(k) for k in known if k and len(str(k)) >= 3 and str(k) in text}
        for value in sorted(found, key=text.find):
            self.alias(value)
        for value in sorted(found, key=len, reverse=True):
            text = text.replace(value, self.forward[value])
        return text

    def restore(self, text: str) -> str:
        """Put the real identifiers back into an LLM answer."""
        for label in sorted(self.backward, key=len, reverse=True):
            text = text.replace(label, self.backward[label])
        return text
