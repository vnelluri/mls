"""Population Stability Index (PSI) computation.

The formula here is the production-real one — what differs between DQ modes
is only *data acquisition*: RealDataQualityService (DQ_MODE=real) bins the
run's actual scoring output via proportions_from_values, while the mock
synthesizes a plausible "current" distribution (deterministically, seeded per
run). Both feed through the same compute_psi.

Conventional reading of the score (matches the platform's default
thresholds): < 0.10 stable, 0.10–0.25 moderate shift (Rework zone),
> 0.25 significant shift (Failed zone).
"""
import math
import random
from bisect import bisect_right
from typing import Dict, List, Optional

# Smoothing to avoid log(0)/division-by-zero on empty buckets.
_EPSILON = 1e-4


def proportions_from_values(values: List[float], bins: List[float]) -> Optional[List[float]]:
    """Bin raw feature values into the baseline's bucket edges and return the
    per-bucket proportions — the real-data path feeding compute_psi. Values
    outside the edge range are clamped into the boundary buckets (standard
    PSI practice: outliers count as extreme-bucket mass, they don't vanish).
    Returns None when there is nothing to bin."""
    if not values or len(bins) < 2:
        return None
    counts = [0] * (len(bins) - 1)
    for v in values:
        idx = bisect_right(bins, v) - 1
        idx = min(max(idx, 0), len(counts) - 1)
        counts[idx] += 1
    total = len(values)
    return [c / total for c in counts]


def compute_psi(expected: List[float], actual: List[float]) -> float:
    """PSI between two bucketed distributions (same bucket edges).

    PSI = Σ (actualᵢ − expectedᵢ) · ln(actualᵢ / expectedᵢ)
    """
    if len(expected) != len(actual):
        raise ValueError("expected and actual must have the same number of buckets")
    psi = 0.0
    for e, a in zip(expected, actual):
        e = max(e, _EPSILON)
        a = max(a, _EPSILON)
        psi += (a - e) * math.log(a / e)
    return round(psi, 4)


def simulate_scoring_proportions(expected: List[float], seed: str) -> List[float]:
    """Synthesize a plausible "current data" distribution from the baseline.

    Local-dev stand-in for binning real scoring output: each bucket's mass is
    perturbed by a seeded log-normal-ish factor and renormalized. The
    perturbation magnitude is drawn per run — mostly small (stable data),
    occasionally large — so, run over run, models show all three monitoring
    statuses just like the fully-synthetic path did. Deterministic for a
    given seed (tenant + model + run id), so a rerun of the same computation
    yields identical PSI.
    """
    rng = random.Random(seed)
    # ~1 in 5 runs drifts hard; the rest hover near the baseline.
    magnitude = rng.uniform(0.55, 1.1) if rng.random() < 0.2 else rng.uniform(0.03, 0.4)
    weights = [max(e, _EPSILON) * math.exp(rng.uniform(-magnitude, magnitude)) for e in expected]
    total = sum(weights)
    return [w / total for w in weights]


def psi_for_baseline(baseline: Dict[str, dict], seed: str) -> Dict[str, float]:
    """Per-feature PSI of a simulated current distribution vs the baseline.

    ``baseline`` is the model's stored driftBaseline:
    {feature: {"bins": [...], "proportions": [...]}}.
    """
    metrics: Dict[str, float] = {}
    for feature, spec in baseline.items():
        expected = [float(p) for p in spec.get("proportions", [])]
        if not expected:
            continue
        actual = simulate_scoring_proportions(expected, f"{seed}:{feature}")
        metrics[feature] = compute_psi(expected, actual)
    return metrics
