"""Turn an agent's markdown reply into text that sounds natural when read aloud.

Code blocks, tables, URLs and long paths are dropped or shortened: you look at the
screen for those. Anything that looks like a secret is replaced before it reaches a
speaker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_HTML = re.compile(r"<[^>\n]{1,200}>")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://[^\s)>\]]+")
_INLINE_CODE = re.compile(r"`([^`\n]*)`")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(.*?)\s*#*\s*$", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+", re.MULTILINE)
_QUOTE = re.compile(r"^\s*>\s?", re.MULTILINE)
_RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$", re.MULTILINE)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1")
_CHECKBOX = re.compile(r"\[( |x|X)\]\s*")
# Something with at least two path separators, or a dotted filename with a line number.
_PATH = re.compile(r"(?<![\w./-])(?:~|\.{1,2})?[\w.@-]*(?:/[\w.@-]+){2,}(?::\d+(?::\d+)?)?")
_FILE_LINE = re.compile(r"\b([\w-]+\.[a-z]{1,5}):(\d+)(?::\d+)?\b")
_MULTISPACE = re.compile(r"[ \t]+")
_MULTINEWLINE = re.compile(r"\n{2,}")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

_SECRETS = [
    re.compile(p)
    for p in (
        r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}\b",  # OpenAI / Anthropic style keys
        r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",  # GitHub tokens
        r"\bAKIA[0-9A-Z]{16}\b",  # AWS access keys
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",  # Slack tokens
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",  # JWTs
        r"\b[A-Fa-f0-9]{32,}\b",  # long hex: hashes, API keys
        r"(?<![\w/+])[A-Za-z0-9+/]{40,}={0,2}(?![\w/+])",  # long base64 blobs
        r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+",
    )
]

_SYMBOLS = [
    (re.compile(r"\s*->\s*"), " to "),
    (re.compile(r"\s*=>\s*"), " gives "),
    (re.compile(r"\s*&&\s*"), " and "),
    (re.compile(r"\s*\|\|\s*"), " or "),
    (re.compile(r"(?<=\w)/(?=\w)"), " or "),  # "input/output" -> "input or output"
]


@dataclass
class Cleaned:
    text: str
    truncated: bool
    dropped_code_blocks: int


def clean(markdown: str, max_chars: int = 700, truncation_suffix: str = "More on screen.") -> Cleaned:
    """Return speakable text for a markdown reply. Empty text means: nothing worth saying."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")

    dropped = len(_FENCE.findall(text))
    text = _FENCE.sub("\n", text)
    # An unterminated fence: drop from the fence to the end.
    if "```" in text:
        text = text.split("```", 1)[0]
        dropped += 1

    text = _TABLE_ROW.sub("", text)
    text = _HTML.sub("", text)
    text = _IMAGE.sub(lambda m: m.group(1), text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _URL.sub("link", text)
    text = _INLINE_CODE.sub(_inline_code, text)
    text = _HEADING.sub(lambda m: _sentence(m.group(1)), text)
    text = _RULE.sub("", text)
    text = _QUOTE.sub("", text)
    text = _CHECKBOX.sub("", text)
    text = _BULLET.sub("", text)
    for _ in range(2):  # nested emphasis like ***x*** or **_x_**
        text = _EMPHASIS.sub(lambda m: m.group(2), text)
    text = _FILE_LINE.sub(lambda m: f"{m.group(1)} line {m.group(2)}", text)
    text = _PATH.sub(_path_basename, text)

    for pattern in _SECRETS:
        text = pattern.sub("redacted", text)
    for pattern, replacement in _SYMBOLS:
        text = pattern.sub(replacement, text)

    # Every line becomes a sentence so the voice pauses between bullets.
    lines = [_sentence(line.strip()) for line in text.split("\n")]
    text = " ".join(line for line in lines if line)
    text = _MULTISPACE.sub(" ", text).strip()
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r"([.!?])\1+", r"\1", text)

    truncated = False
    if max_chars and len(text) > max_chars:
        text = _cut_at_sentence(text, max_chars)
        truncated = True
        if truncation_suffix:
            text = f"{text} {truncation_suffix}"

    # Nothing but code or symbols: say nothing.
    if not re.search(r"[A-Za-z]{2,}", text):
        text = ""
    return Cleaned(text=text, truncated=truncated, dropped_code_blocks=dropped)


def _inline_code(match: re.Match) -> str:
    code = match.group(1).strip()
    if not code or len(code) > 40:
        return ""
    return code


def _path_basename(match: re.Match) -> str:
    path = match.group(0)
    line = ""
    if ":" in path:
        path, _, rest = path.partition(":")
        line = f" line {rest.split(':')[0]}"
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return f"{name}{line}" if name else ""


def _sentence(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if line[-1] not in ".!?:;,":
        line += "."
    elif line[-1] in ":;,":
        line = line[:-1] + "."
    return line


def _cut_at_sentence(text: str, max_chars: int) -> str:
    head = text[:max_chars]
    parts = _SENTENCE_END.split(head)
    if len(parts) > 1:
        kept = " ".join(parts[:-1]).strip()
        if len(kept) >= max_chars // 3:
            return kept
    # No sentence boundary in range: cut at a word.
    cut = head.rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "."
