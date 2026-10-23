"""Semantic violation cause taxonomy for broken scheduling policies."""
from enum import Enum


class CauseTaxonomy(str, Enum):
    # The labels are evidence classes, not guesses.  The classifier documents
    # the corresponding IR/analysis predicates in classify.py.
    NO_AGING = "NO_AGING"
    AGING_TOO_SLOW = "AGING_TOO_SLOW"
    TIER_CONTENTION = "TIER_CONTENTION"
    QUANTUM_IMBALANCE = "QUANTUM_IMBALANCE"
    OVERPROMISED_BOUND = "OVERPROMISED_BOUND"
    SHARE_INFEASIBLE = "SHARE_INFEASIBLE"
    UNKNOWN_CONSERVATIVE = "UNKNOWN_CONSERVATIVE"
