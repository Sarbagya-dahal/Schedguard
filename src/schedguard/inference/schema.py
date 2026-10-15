"""Property library + strict validation. AI output is UNTRUSTED: only guarantees
that fit this library, reference real classes and respect the numeric ranges are
accepted. Everything else is rejected with a reason (never silently repaired)."""
import json, re
from ..ir import IRPolicy, IRGuarantee
from .. import limits as L

LIBRARY = {
    "no_starvation": {"field": "bound_ms", "range": L.BOUND_MS_RANGE, "unit": "ms",
                      "meaning": "every task of the class is dispatched within bound_ms of becoming ready"},
    "min_share": {"field": "percent", "range": L.SHARE_PCT_RANGE, "unit": "%",
                  "meaning": "the class gets at least `percent` of CPU time under any workload"},
}
MAX_PROPOSALS = 8


def extract_json(text: str):
    t = text.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        idx = t.find("{", pos)
        if idx == -1:
            break
        try:
            obj, _ = decoder.raw_decode(t, idx=idx)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        pos = idx + 1
    raise ValueError("no JSON object in model output")


def validate(raw_text: str, ir: IRPolicy):
    """-> (accepted: list[IRGuarantee], rejected: list[(item, reason)], rationale: str)"""
    try:
        obj = extract_json(raw_text)
    except Exception as e:
        return [], [(raw_text[:200], f"unparseable: {e}")], ""
    items = obj.get("guarantees") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        return [], [(str(obj)[:200], "missing 'guarantees' list")], ""
    names = {c.name: c.idx for c in ir.classes}
    accepted, rejected, seen = [], [], set()
    for k, it in enumerate(items):
        if k >= MAX_PROPOSALS:
            rejected.append((it, f"more than {MAX_PROPOSALS} proposals"))
            continue
        if not isinstance(it, dict):
            rejected.append((it, "not an object")); continue
        kind, cls = it.get("type"), it.get("class")
        spec = LIBRARY.get(kind)
        if spec is None:
            rejected.append((it, f"type {kind!r} not in property library")); continue
        if cls not in names:
            rejected.append((it, f"unknown class {cls!r}")); continue
        val = it.get(spec["field"])
        if isinstance(val, bool) or not isinstance(val, int):
            rejected.append((it, f"{spec['field']} must be an integer")); continue
        lo, hi = spec["range"]
        if not lo <= val <= hi:
            rejected.append((it, f"{spec['field']}={val} outside [{lo},{hi}]")); continue
        key = (kind, cls, val)
        if key in seen:
            rejected.append((it, "duplicate")); continue
        seen.add(key)
        accepted.append(IRGuarantee(kind, names[cls], cls, val))
    rationale = obj.get("rationale", "") if isinstance(obj.get("rationale", ""), str) else ""
    return accepted, rejected, rationale
