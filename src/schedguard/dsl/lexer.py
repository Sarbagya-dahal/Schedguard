"""Hand-written lexer (syllabus Module 1: tokens, lexemes, regex specification)."""
import re
from dataclasses import dataclass


class DSLError(Exception):
    def __init__(self, msg: str, line: int = 0, col: int = 0):
        super().__init__(f"line {line}, col {col}: {msg}" if line else msg)
        self.msg, self.line, self.col = msg, line, col


KEYWORDS = {"policy", "class", "prio", "quantum", "aging", "kind", "guarantee",
            "option", "max_tasks", "no_starvation", "min_share", "ms", "adapt", "in"}

_SPEC = [
    ("COMMENT", r"//[^\n]*"),
    ("WS", r"[ \t\r]+"),
    ("NL", r"\n"),
    ("RANGE", r"\.\."),
    ("DOT", r"\."),
    ("INT", r"\d+"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("PUNCT", r"[{}();,=%]"),
]
_RE = re.compile("|".join(f"(?P<{n}>{p})" for n, p in _SPEC))


@dataclass(frozen=True)
class Token:
    kind: str   # KW, IDENT, INT, PUNCT, RANGE, DOT, EOF
    text: str
    line: int
    col: int


def tokenize(src: str) -> list[Token]:
    toks, pos, line, line_start = [], 0, 1, 0
    while pos < len(src):
        m = _RE.match(src, pos)
        if not m:
            raise DSLError(f"unexpected character {src[pos]!r}", line, pos - line_start + 1)
        kind, text = m.lastgroup, m.group()
        col = pos - line_start + 1
        if kind == "NL":
            line += 1
            line_start = m.end()
        elif kind == "IDENT":
            toks.append(Token("KW" if text in KEYWORDS else "IDENT", text, line, col))
        elif kind in ("INT", "PUNCT", "RANGE", "DOT"):
            toks.append(Token(kind, text, line, col))
        pos = m.end()
    toks.append(Token("EOF", "", line, pos - line_start + 1))
    return toks
