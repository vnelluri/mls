"""
Data quality check step execution -- mock/real split selected by DQ_MODE.

Both implementations return the same dict shape, feeding directly into
monitoring_service's snapshot builder: requestCount, avgLatencyMs, errorRate,
driftMetrics, driftComputation, dataQualityPassed, dataQualityDetails.

MockDataQualityService (DQ_MODE=mock, the default) is pure synthetic — demo
numbers, seeded-PSI simulation when a drift baseline exists. See the v1 notes
inline.

RealDataQualityService (DQ_MODE=real) computes every number from the run's
actual scoring output: parquet files under the step's `inputS3Uri`, read via
S3 up to a DQ_MAX_BYTES budget (bounding both memory and how long the step
can hold a refresh pass). Semantics:

  * requestCount        -- rows scored (row count of the output read)
  * errorRate           -- null fraction of the configured `predictionColumn`
                           (a row the model failed to score is an error);
                           0.0 when no predictionColumn is configured
  * null_rate check     -- null fraction of the column named by the check;
                           a check naming a missing column FAILS (observed
                           1.0) rather than silently passing
  * row_count_delta     -- |rows - previous run's rows| / previous, where
                           "previous" is the model's latest monitoring
                           snapshot; 0.0 on the first run
  * schema_match        -- fraction of the drift baseline's features missing
                           from the output columns; 0.0 with no baseline
  * driftMetrics        -- real per-feature PSI: actual column values binned
                           into the baseline's bucket edges vs its stored
                           proportions. No baseline -> no drift numbers
                           (driftComputation="none": the real engine never
                           fabricates evidence)
  * avgLatencyMs        -- 0.0 (batch scoring has no request latency)

Failures to read the output at all (no parquet files, unreadable files) raise
— job_service fails the step, which is correct: a run whose output cannot be
inspected must not pass its quality gate.
"""
import logging
import random
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.services import psi

logger = logging.getLogger(__name__)

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


def validate_real_config() -> None:
    """Fail fast at startup when DQ_MODE=real is enabled without its engine
    dependency installed."""
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("DQ_MODE=real requires the pyarrow package") from exc


class MockDataQualityService:
    def execute(
        self,
        step_config: dict,
        drift_baseline: Optional[Dict[str, dict]] = None,
        drift_seed: Optional[str] = None,
        previous_row_count: Optional[int] = None,
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


# ---------------------------------------------------------------------------
# Real engine
# ---------------------------------------------------------------------------

def _parse_s3_uri(uri: str) -> Tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"inputS3Uri '{uri}' is not an s3:// URI")
    bucket, _, prefix = uri[len("s3://"):].partition("/")
    if not bucket:
        raise ValueError(f"inputS3Uri '{uri}' has no bucket")
    return bucket, prefix


class RealDataQualityService:
    """Computes quality/drift evidence from the run's actual scoring output."""

    def execute(
        self,
        step_config: dict,
        drift_baseline: Optional[Dict[str, dict]] = None,
        drift_seed: Optional[str] = None,
        previous_row_count: Optional[int] = None,
    ) -> Dict:
        table, read_stats = self._read_scoring_output(step_config["inputS3Uri"])
        row_count = table.num_rows
        columns = set(table.column_names)

        error_rate = self._error_rate(table, step_config.get("predictionColumn"))
        drift_metrics, drift_computation, drift_skipped = self._drift(table, drift_baseline)

        checks = step_config.get("checks", [])
        data_quality_details = {}
        data_quality_passed = True
        for i, check in enumerate(checks):
            check_type = check["type"]
            name = (check.get("name") or "").strip() or f"{check_type}_{i + 1}"
            threshold = float(check["threshold"])
            observed, note = self._observed(
                check_type, name, table, columns, row_count, previous_row_count, drift_baseline
            )
            passed = observed <= threshold
            if not passed:
                data_quality_passed = False
            detail = {"passed": passed, "observedValue": round(observed, 4)}
            if note:
                detail["note"] = note
            data_quality_details[name] = detail

        result = {
            "requestCount": row_count,
            "avgLatencyMs": 0.0,  # batch scoring: no request latency exists
            "errorRate": round(error_rate, 4),
            "driftMetrics": drift_metrics,
            "driftComputation": drift_computation,
            "dataQualityPassed": data_quality_passed,
            "dataQualityDetails": data_quality_details,
            "inputRead": read_stats,
        }
        if drift_skipped:
            result["driftSkippedFeatures"] = drift_skipped
        return result

    # -- S3 / parquet ------------------------------------------------------

    def _read_scoring_output(self, input_s3_uri: str):
        """All parquet files under the prefix, within the DQ_MAX_BYTES
        budget. Zero readable output raises — that is itself a quality
        failure, not something to shrug past."""
        import boto3
        import pyarrow as pa
        import pyarrow.parquet as pq

        bucket, prefix = _parse_s3_uri(input_s3_uri)
        s3 = boto3.client("s3", region_name=settings.AWS_REGION)

        objects: List[dict] = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects.extend(page.get("Contents", []))
        parquet_objects = [o for o in objects if o["Key"].endswith(".parquet")]
        if not parquet_objects:
            raise ValueError(
                f"No parquet files found under {input_s3_uri} — no scoring output to check"
            )

        selected, skipped, bytes_selected = [], 0, 0
        for obj in parquet_objects:
            if bytes_selected + obj["Size"] > settings.DQ_MAX_BYTES and selected:
                skipped += 1
                continue
            if obj["Size"] > settings.DQ_MAX_BYTES:
                raise ValueError(
                    f"Scoring output file s3://{bucket}/{obj['Key']} ({obj['Size']} bytes) "
                    f"exceeds DQ_MAX_BYTES={settings.DQ_MAX_BYTES}; raise the budget or "
                    "shrink the unload file size"
                )
            selected.append(obj)
            bytes_selected += obj["Size"]

        tables = []
        for obj in selected:
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            tables.append(pq.read_table(BytesIO(body)))
        table = tables[0] if len(tables) == 1 else pa.concat_tables(tables, promote_options="default")

        read_stats = {
            "filesRead": len(selected),
            "filesSkipped": skipped,
            "bytesRead": bytes_selected,
            "sampled": skipped > 0,
        }
        if skipped:
            logger.warning(
                "DQ read sampled %d/%d parquet files under %s (DQ_MAX_BYTES=%d)",
                len(selected), len(parquet_objects), input_s3_uri, settings.DQ_MAX_BYTES,
            )
        return table, read_stats

    # -- metric computations -------------------------------------------------

    @staticmethod
    def _null_fraction(table, column: str) -> float:
        if table.num_rows == 0:
            return 0.0
        return table.column(column).null_count / table.num_rows

    def _error_rate(self, table, prediction_column: Optional[str]) -> float:
        if not prediction_column:
            return 0.0
        if prediction_column not in table.column_names:
            # A configured prediction column that isn't in the output means
            # nothing was scored as far as we can verify.
            return 1.0
        return self._null_fraction(table, prediction_column)

    def _observed(
        self,
        check_type: str,
        name: str,
        table,
        columns: set,
        row_count: int,
        previous_row_count: Optional[int],
        drift_baseline: Optional[Dict[str, dict]],
    ) -> Tuple[float, Optional[str]]:
        """(observed value, optional note) for one configured check. The
        check's `name` is the column it targets for null_rate."""
        if check_type == "null_rate":
            if name in columns:
                return self._null_fraction(table, name), None
            return 1.0, f"column '{name}' not found in scoring output — check fails"

        if check_type == "row_count_delta":
            if not previous_row_count:
                return 0.0, "first run — no previous row count to compare"
            return abs(row_count - previous_row_count) / previous_row_count, None

        # schema_match: the expected schema is the drift baseline's features.
        expected = set((drift_baseline or {}).keys())
        if not expected:
            return 0.0, "no drift baseline registered — no expected schema to compare"
        missing = sorted(expected - columns)
        observed = len(missing) / len(expected)
        note = f"missing expected columns: {missing}" if missing else None
        return observed, note

    @staticmethod
    def _drift(table, drift_baseline: Optional[Dict[str, dict]]):
        """Real per-feature PSI: bin the output's actual values into the
        baseline's bucket edges and compare against its stored proportions.
        Features absent from the output (or non-numeric) are skipped and
        reported, never guessed."""
        if not drift_baseline:
            return {}, "none", []

        metrics: Dict[str, float] = {}
        skipped: List[str] = []
        for feature, spec in drift_baseline.items():
            expected = [float(p) for p in spec.get("proportions", [])]
            bins = [float(b) for b in spec.get("bins", [])]
            if not expected or len(bins) != len(expected) + 1:
                skipped.append(feature)
                continue
            if feature not in table.column_names:
                skipped.append(feature)
                continue
            values = []
            for v in table.column(feature).to_pylist():
                if v is None:
                    continue
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    values = []
                    break  # non-numeric column: cannot bin against the baseline
            actual = psi.proportions_from_values(values, bins)
            if actual is None:
                skipped.append(feature)
                continue
            metrics[feature] = psi.compute_psi(expected, actual)
        return metrics, "psi_vs_baseline", skipped


def get_data_quality_service():
    if settings.DQ_MODE == "real":
        return RealDataQualityService()
    return MockDataQualityService()
