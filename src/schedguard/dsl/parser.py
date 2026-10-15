"""Recursive-descent parser (syllabus Module 2). The grammar is LL(1):

  policy    := 'policy' IDENT '{' item* '}' EOF
  item      := 'class' IDENT '{' attr* '}'
             | 'guarantee' gspec ';'
             | 'option' 'max_tasks' '=' INT ';'
  attr      := 'prio' INT ';' | 'quantum' INT 'ms' ';'
             | 'aging' INT 'ms' ';' | 'kind' IDENT ';'
  gspec     := 'no_starvation' '(' IDENT ',' INT 'ms' ')'
             | 'min_share' '(' IDENT ',' INT '%' ')'
"""
from .lexer import tokenize, Token, DSLError
from .ast_nodes import PolicyAST, ClassDecl, GuaranteeDecl, AdaptDecl


class _Parser:
    def __init__(self, toks: list[Token]):
        self.t, self.i = toks, 0

    @property
    def cur(self) -> Token:
        return self.t[self.i]

    def err(self, want: str):
        c = self.cur
        got = c.text or "end of input"
        raise DSLError(f"expected {want}, found {got!r}", c.line, c.col)

    def eat(self, text: str | None = None, kind: str | None = None) -> Token:
        c = self.cur
        if (text is not None and c.text != text) or (kind is not None and c.kind != kind):
            self.err(repr(text) if text else kind)
        self.i += 1
        return c

    def int_(self) -> int:
        return int(self.eat(kind="INT").text)

    def policy(self) -> PolicyAST:
        self.eat("policy")
        pol = PolicyAST(self.eat(kind="IDENT").text)
        self.eat("{")
        while self.cur.text != "}":
            if self.cur.kind == "EOF":
                self.err("'}'")
            self.item(pol)
        self.eat("}")
        self.eat(kind="EOF")
        return pol

    def item(self, pol: PolicyAST):
        c = self.cur
        if c.text == "class":
            self.eat()
            decl = ClassDecl(self.eat(kind="IDENT").text, c.line)
            self.eat("{")
            while self.cur.text != "}":
                if self.cur.kind == "EOF":
                    self.err("'}'")
                self.attr(decl)
            self.eat("}")
            pol.classes.append(decl)
        elif c.text == "guarantee":
            self.eat()
            pol.guarantees.append(self.gspec(c.line))
            self.eat(";")
        elif c.text == "option":
            self.eat()
            self.eat("max_tasks")
            self.eat("=")
            pol.max_tasks = self.int_()
            self.eat(";")
        elif c.text == "adapt":
            self.eat()
            cls = self.eat(kind="IDENT").text
            self.eat(kind="DOT")
            param_tok = self.eat()
            param = param_tok.text
            if param not in ("aging", "quantum"):
                raise DSLError(f"expected 'aging' or 'quantum', found {param!r}", param_tok.line, param_tok.col)
            self.eat("in")
            lo = self.int_()
            self.eat("ms")
            self.eat(kind="RANGE")
            hi = self.int_()
            self.eat("ms")
            self.eat(";")
            pol.adaptations.append(AdaptDecl(cls, param, lo, hi, c.line))
        else:
            self.err("'class', 'guarantee', 'adapt' or 'option'")

    def attr(self, d: ClassDecl):
        c = self.cur
        if c.text == "prio":
            self.eat(); d.prio = self.int_()
        elif c.text == "quantum":
            self.eat(); d.quantum_ms = self.int_(); self.eat("ms")
        elif c.text == "aging":
            self.eat(); d.aging_ms = self.int_(); self.eat("ms")
        elif c.text == "kind":
            self.eat(); d.kind = self.eat(kind="IDENT").text
        else:
            self.err("'prio', 'quantum', 'aging' or 'kind'")
        self.eat(";")

    def gspec(self, line: int) -> GuaranteeDecl:
        c = self.cur
        if c.text == "no_starvation":
            self.eat(); self.eat("(")
            cls = self.eat(kind="IDENT").text
            self.eat(","); v = self.int_(); self.eat("ms"); self.eat(")")
            return GuaranteeDecl("no_starvation", cls, v, line)
        if c.text == "min_share":
            self.eat(); self.eat("(")
            cls = self.eat(kind="IDENT").text
            self.eat(","); v = self.int_(); self.eat("%"); self.eat(")")
            return GuaranteeDecl("min_share", cls, v, line)
        self.err("'no_starvation' or 'min_share'")


def parse(src: str) -> PolicyAST:
    return _Parser(tokenize(src)).policy()
