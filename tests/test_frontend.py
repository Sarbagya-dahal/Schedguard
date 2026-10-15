import pytest
from schedguard.dsl import parse, DSLError
from schedguard.dsl.lexer import tokenize
from schedguard.compiler import compile_source

GOOD = """policy p { option max_tasks = 4;
  class a { prio 0; quantum 5 ms; kind batch; }
  class b { prio 1; quantum 10 ms; aging 100 ms; }
  guarantee no_starvation(b, 500 ms); guarantee min_share(a, 20 %); }"""


def test_lexer_tracks_lines_and_skips_comments():
    toks = tokenize("// hi\npolicy x {}")
    assert toks[0].text == "policy" and toks[0].line == 2


def test_lexer_rejects_bad_char():
    with pytest.raises(DSLError):
        tokenize("policy $ {}")


def test_parse_good():
    ast = parse(GOOD)
    assert [c.name for c in ast.classes] == ["a", "b"]
    assert ast.guarantees[1].kind == "min_share" and ast.max_tasks == 4


@pytest.mark.parametrize("src", ["policy {", "policy p { class a { prio 1 } }",
                                 "policy p { guarantee nope(a, 1 ms); }", "policy p { } extra"])
def test_parse_errors(src):
    with pytest.raises(DSLError):
        parse(src)


def test_lowering_resolves_indices():
    r = compile_source(GOOD)
    assert r.ok and r.ir.guarantees[0].cls_idx == 1 and r.ir.classes[1].aging_ms == 100


def test_safety_pass_catches_everything():
    r = compile_source("policy p { class a { prio 9; quantum 0 ms; } class a { quantum 5 ms; } "
                       "guarantee min_share(zz, 500 %); }")
    codes = {d.code for d in r.diagnostics}
    assert {"E004", "E006", "E007", "E009", "E010"} <= codes and r.ir is None


def test_missing_quantum_and_too_many_classes():
    assert "E005" in {d.code for d in compile_source("policy p { class a { prio 0; } }").diagnostics}
    many = "policy p { " + " ".join(f"class c{i} {{ quantum 1 ms; }}" for i in range(17)) + " }"
    assert "E002" in {d.code for d in compile_source(many).diagnostics}


def test_safety_pass_remaining_codes():
    assert "E001" in {d.code for d in compile_source("policy p {}").diagnostics}
    assert "E003" in {d.code for d in compile_source("policy p { option max_tasks = 999; class a { quantum 1 ms; } }").diagnostics}
    assert "E008" in {d.code for d in compile_source("policy p { class a { quantum 1 ms; aging 999999 ms; } }").diagnostics}
