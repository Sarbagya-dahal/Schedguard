"""Tests for violation cause taxonomy and deterministic classifier."""
import pytest
from schedguard.ir import IRClass, IRPolicy, IRGuarantee
from schedguard.verify.properties import check_guarantee


def test_classify_no_aging():
    from schedguard.repair.taxonomy import CauseTaxonomy
    from schedguard.repair.classify import classify_violation

    c0 = IRClass(0, "web", 0, 5, 0, "interactive")
    c1 = IRClass(1, "batch", 1, 20, 0, "batch") # no aging
    g = IRGuarantee("no_starvation", 1, "batch", 500)
    pol = IRPolicy("p_no_aging", (c0, c1), (g,), max_tasks=8)

    v = check_guarantee(pol, g)
    assert v.status == "VIOLATED"

    res = classify_violation(pol, v)
    assert res.cause == CauseTaxonomy.NO_AGING
    assert "aging" in res.explanation.lower()
    assert res.suggested_fix


def test_classify_aging_too_slow():
    from schedguard.repair.taxonomy import CauseTaxonomy
    from schedguard.repair.classify import classify_violation

    c0 = IRClass(0, "web", 0, 5, 0, "interactive")
    c1 = IRClass(1, "batch", 1, 20, 800, "batch") # aging is 800ms
    g = IRGuarantee("no_starvation", 1, "batch", 300) # promises 300ms!
    pol = IRPolicy("p_slow_aging", (c0, c1), (g,), max_tasks=8)

    v = check_guarantee(pol, g)
    assert v.status == "VIOLATED"

    res = classify_violation(pol, v)
    assert res.cause == CauseTaxonomy.AGING_TOO_SLOW
    assert "aging" in res.explanation.lower()


def test_classify_overpromised_bound():
    from schedguard.repair.taxonomy import CauseTaxonomy
    from schedguard.repair.classify import classify_violation

    c0 = IRClass(0, "web", 0, 10, 0, "interactive")
    # Declares bound of 5ms for web, but quantum is 10ms!
    g = IRGuarantee("no_starvation", 0, "web", 5)
    pol = IRPolicy("p_overpromised", (c0,), (g,), max_tasks=8)

    v = check_guarantee(pol, g)
    assert v.status == "VIOLATED"

    res = classify_violation(pol, v)
    assert res.cause == CauseTaxonomy.OVERPROMISED_BOUND


def test_classify_share_infeasible():
    from schedguard.repair.taxonomy import CauseTaxonomy
    from schedguard.repair.classify import classify_violation

    c0 = IRClass(0, "web", 0, 5, 0, "interactive")
    c1 = IRClass(1, "batch", 1, 20, 100, "batch")
    # Batch promises 90% min share, but web has top priority!
    g = IRGuarantee("min_share", 1, "batch", 90)
    pol = IRPolicy("p_bad_share", (c0, c1), (g,), max_tasks=8)

    v = check_guarantee(pol, g)
    assert v.status == "VIOLATED"

    res = classify_violation(pol, v)
    assert res.cause == CauseTaxonomy.SHARE_INFEASIBLE
