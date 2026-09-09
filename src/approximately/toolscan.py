"""Static analyzer for tool descriptions: catch poisoning before it loads.

Tool poisoning hides instructions in tool metadata where the user can't
see them but the model can (Invariant Labs' disclosure; MCPTox found it
common in the wild). This scanner runs the cheap deterministic half of
detection — no model needed:

- invisible characters: zero-width joiners/spaces, word joiners, BOM
- bidi attacks: direction overrides/isolates that reorder rendered text
- script mixing: Cyrillic/Greek homoglyphs inside Latin text
- injection phrasing: "ignore previous instructions", exfiltration
  patterns, covert-channel hints (base64 blobs, curl posts)

Verdicts: clean / suspicious / malicious (invisible or bidi characters
are malicious on sight — no legitimate tool description needs them).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List

INVISIBLE = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u2060": "word joiner",
    "\ufeff": "zero-width no-break space (BOM)",
}
BIDI = {chr(c): "bidi control" for c in
        list(range(0x202A, 0x202F)) + list(range(0x2066, 0x2070))}

INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",
     "instruction override"),
    (r"disregard\s+(all\s+)?(previous|prior|your)", "instruction override"),
    (r"(do not|don'?t)\s+(tell|reveal|mention|inform)", "concealment"),
    (r"(secretly|silent(ly)?|covert(ly)?)\s+(send|post|forward|upload)",
     "covert exfiltration"),
    ((r"(send|post|upload|forward)\s+(the\s+)?(all\s+)?"
      r"(data|context|conversation|credentials?|keys?|tokens?)"
      r"\s+(to|via)\s+(https?://|curl)"),
     "exfiltration endpoint"),
    (r"\b(base64|b64)\b.{0,40}(encode|include|embed)", "encoded payload"),
    (r"(before|when)\s+(you\s+)?respond(ing)?[, ]", "response interception"),
    (r"system\s+prompt", "system-prompt probing"),
]


@dataclass
class Finding:
    kind: str
    detail: str
    position: int = -1  # character offset, -1 = whole text

    def __str__(self) -> str:
        at = f" at offset {self.position}" if self.position >= 0 else ""
        return f"[{self.kind}]{at} {self.detail}"


@dataclass
class ScanResult:
    verdict: str  # clean / suspicious / malicious
    findings: List[Finding] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.verdict == "clean"

    def summary(self) -> str:
        if not self.findings:
            return "clean: no poisoning indicators found"
        lines = [f"{self.verdict.upper()}: {len(self.findings)} finding(s)"]
        lines.extend(f"  - {finding}" for finding in self.findings)
        return "\n".join(lines)


def scan(description: str) -> ScanResult:
    findings: List[Finding] = []

    for ch, name in {**INVISIBLE, **BIDI}.items():
        pos = description.find(ch)
        while pos != -1:
            kind = "bidi-attack" if ch in BIDI else "invisible-character"
            findings.append(Finding(kind, f"{name} U+{ord(ch):04X}", pos))
            pos = description.find(ch, pos + 1)

    scripts = set()
    for ch in description:
        if ch.isalpha():
            try:
                name = unicodedata.name(ch)
            except ValueError:
                continue
            scripts.add(name.split()[0])
    latin = "LATIN" in scripts or not scripts
    foreign = {s for s in scripts if s in ("CYRILLIC", "GREEK", "ARMENIAN")}
    if latin and foreign:
        findings.append(Finding(
            "homoglyph-mixing",
            f"Latin text mixed with {', '.join(sorted(foreign))} letters "
            "(classic homoglyph camouflage)", 0))

    lowered = description.lower()
    for pattern, kind in INJECTION_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            findings.append(Finding("injection-phrasing",
                                    f"{kind}: “{match.group(0)}”",
                                    match.start()))

    malicious = any(f.kind in ("bidi-attack", "invisible-character")
                    for f in findings)
    suspicious = sum(1 for f in findings
                     if f.kind in ("injection-phrasing", "homoglyph-mixing"))
    if malicious:
        verdict = "malicious"
    elif suspicious:
        verdict = "suspicious"
    else:
        verdict = "clean"
    return ScanResult(verdict=verdict, findings=findings)
