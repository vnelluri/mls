"""
Data quality check step execution -- mock only for v1 (mirrors the same
mock/real split pattern as data_pipeline_service, but a "real" DQ engine is
well out of scope here; MockDataQualityService is the only implementation).

execute() returns a dict shaped to feed directly into monitoring_service's
snapshot builder: requestCount, avgLatencyMs, errorRate, driftMetrics,
dataQualityPassed, dataQualityDetails.

Drift metrics come from one of two paths (result carries which in
``driftComputation``):

  * ``psi_vs_baseline`` — the model was registered with a ``driftBaseline``
    (per-feature training-time distributions): PSI is computed with the real
    formula (services/psi.py) against a deterministic, seeded simulation of
    the current data. Same run → same numbers.
  * ``synthetic`` — no baseline registered: per-feature PSI values are drawn
    randomly (the original v1 behavior), purely for demo purposes.
"""
import random
from typing import Dict, Optional

from app.services import psi

_FEATURE_POOL = [
    "credit_score",
    "annual_income",
    "debt_to_income_ratio",
    "account_age_days",
    "num_open_lines",
    "transaction_velocity",
    "avg_balance_30d",
    "geo_risk_score",
]


class MockDataQualityService:
    def execute(
        self,
        step_config: dict,
        drift_baseline: Optional[Dict[str, dict]] = None,
        drift_seed: Optional[str] = None,
    ) -> Dict:
        request_count = random.randint(100, 5000)
        avg_latency_ms = round(random.uniform(20, 200), 2)

        # Error rate: mostly low, occasional demo-friendly spike.
        if random.random() < 0.15:
            error_rate = round(random.uniform(0.12, 0.22), 4)
        else:
            error_rate = round(random.uniform(0.0, 0.08), 4)

        if drift_baseline:
            # Real PSI against the registered training-time baseline
            # (deterministic per run — see services/psi.py).
            drift_metrics = psi.psi_for_baseline(drift_baseline, drift_seed or "no-seed")
            drift_computation = "psi_vs_baseline"
        else:
            # No baseline registered: synthetic drift numbers (v1 behavior) —
            # 2-4 features, PSI mostly low but occasionally spiking past
            # warn/fail thresholds so demo data shows all 3 real statuses.
            num_features = random.randint(2, 4)
            features = random.sample(_FEATURE_POOL, num_features)
            drift_metrics = {}
            for feature in features:
                if random.random() < 0.2:
                    drift_metrics[feature] = round(random.uniform(0.10, 0.30), 4)
                else:
                    drift_metrics[feature] = round(random.uniform(0.0, 0.09), 4)
            drift_computation = "synthetic"

        checks = step_config.get("checks", [])
        data_quality_details = {}
        data_quality_passed = True
        for i, check in enumerate(checks):
            check_type = check["type"]
            # DynamoDB map keys must be non-empty; a check saved with a blank
            # name would corrupt the job item on write, so fall back to a
            # generated key. (New pipelines reject blank names at creation.)
            name = (check.get("name") or "").strip() or f"{check_type}_{i + 1}"
            threshold = float(check["threshold"])

            if check_type == "null_rate":
                # Meaningful synthetic null rate: usually passes a sane
                # threshold (~0.08) but fails often enough to demo DQ failures.
                observed = round(random.uniform(0.0, 0.09), 4)
            elif check_type == "row_count_delta":
                observed = round(random.uniform(0.0, 0.16), 4)
            else:  # schema_match
                observed = round(random.uniform(0.0, 0.04), 4)

            passed = observed <= threshold
            if not passed:
                data_quality_passed = False
            data_quality_details[name] = {"passed": passed, "observedValue": observed}

        # If no checks were configured on the step, there is nothing to fail.
        if not checks:
            data_quality_passed = True

        return {
            "requestCount": request_count,
            "avgLatencyMs": avg_latency_ms,
            "errorRate": error_rate,
            "driftMetrics": drift_metrics,
            "driftComputation": drift_computation,
            "dataQualityPassed": data_quality_passed,
            "dataQualityDetails": data_quality_details,
        }


def get_data_quality_service() -> MockDataQualityService:
    return MockDataQualityService()
