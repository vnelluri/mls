"""RealDataQualityService unit tests: parquet scoring output on (moto) S3 in,
real quality/drift evidence out. No monkeypatched math — the numbers asserted
here are computed from the actual file contents."""
from io import BytesIO

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from moto import mock_aws

from app.config import settings
from app.services.data_quality_service import RealDataQualityService

BUCKET = "scoring-out"
PREFIX = "fraud/daily"
INPUT_URI = f"s3://{BUCKET}/{PREFIX}"


def parquet_bytes(columns: dict) -> bytes:
    buf = BytesIO()
    pq.write_table(pa.table(columns), buf)
    return buf.getvalue()


@pytest.fixture()
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def put_output(s3, columns: dict, key: str = f"{PREFIX}/part-000.parquet") -> None:
    s3.put_object(Bucket=BUCKET, Key=key, Body=parquet_bytes(columns))


def dq_config(checks=None, prediction_column=None) -> dict:
    config = {"checks": checks or [], "inputS3Uri": INPUT_URI}
    if prediction_column:
        config["predictionColumn"] = prediction_column
    return config


class TestReadAndShape:
    def test_counts_rows_and_reports_read_stats(self, s3):
        put_output(s3, {"prediction": [0.1, 0.9, 0.4], "credit_score": [650, 700, 720]})
        result = RealDataQualityService().execute(dq_config())
        assert result["requestCount"] == 3
        assert result["avgLatencyMs"] == 0.0
        assert result["inputRead"] == {
            "filesRead": 1, "filesSkipped": 0,
            "bytesRead": result["inputRead"]["bytesRead"], "sampled": False,
        }
        assert result["dataQualityPassed"] is True

    def test_concatenates_multiple_parquet_files(self, s3):
        put_output(s3, {"prediction": [0.1, 0.2]}, key=f"{PREFIX}/part-000.parquet")
        put_output(s3, {"prediction": [0.3]}, key=f"{PREFIX}/part-001.parquet")
        result = RealDataQualityService().execute(dq_config())
        assert result["requestCount"] == 3
        assert result["inputRead"]["filesRead"] == 2

    def test_no_parquet_files_raises(self, s3):
        s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}/_SUCCESS", Body=b"")
        with pytest.raises(ValueError, match="No parquet files found"):
            RealDataQualityService().execute(dq_config())

    def test_byte_budget_samples_later_files(self, s3, monkeypatch):
        body = parquet_bytes({"prediction": [0.1, 0.2]})
        s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}/part-000.parquet", Body=body)
        s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}/part-001.parquet", Body=body)
        monkeypatch.setattr(settings, "DQ_MAX_BYTES", len(body) + 1)
        result = RealDataQualityService().execute(dq_config())
        assert result["requestCount"] == 2  # only the first file was read
        assert result["inputRead"]["filesSkipped"] == 1
        assert result["inputRead"]["sampled"] is True

    def test_single_file_over_budget_raises(self, s3, monkeypatch):
        put_output(s3, {"prediction": [0.1, 0.2, 0.3]})
        monkeypatch.setattr(settings, "DQ_MAX_BYTES", 10)
        with pytest.raises(ValueError, match="exceeds DQ_MAX_BYTES"):
            RealDataQualityService().execute(dq_config())


class TestErrorRate:
    def test_null_predictions_are_errors(self, s3):
        put_output(s3, {"prediction": [0.1, None, 0.4, None]})
        result = RealDataQualityService().execute(dq_config(prediction_column="prediction"))
        assert result["errorRate"] == 0.5

    def test_missing_prediction_column_is_total_failure(self, s3):
        put_output(s3, {"score": [0.1, 0.2]})
        result = RealDataQualityService().execute(dq_config(prediction_column="prediction"))
        assert result["errorRate"] == 1.0

    def test_no_prediction_column_configured_reports_zero(self, s3):
        put_output(s3, {"score": [0.1, None]})
        result = RealDataQualityService().execute(dq_config())
        assert result["errorRate"] == 0.0


class TestChecks:
    def test_null_rate_measures_named_column(self, s3):
        put_output(s3, {"credit_score": [650, None, 720, 700]})
        result = RealDataQualityService().execute(
            dq_config(checks=[{"name": "credit_score", "type": "null_rate", "threshold": 0.30}])
        )
        detail = result["dataQualityDetails"]["credit_score"]
        assert detail["observedValue"] == 0.25
        assert detail["passed"] is True
        assert result["dataQualityPassed"] is True

    def test_null_rate_fails_past_threshold(self, s3):
        put_output(s3, {"credit_score": [650, None, None, None]})
        result = RealDataQualityService().execute(
            dq_config(checks=[{"name": "credit_score", "type": "null_rate", "threshold": 0.30}])
        )
        assert result["dataQualityDetails"]["credit_score"]["passed"] is False
        assert result["dataQualityPassed"] is False

    def test_null_rate_on_missing_column_fails_loudly(self, s3):
        put_output(s3, {"other": [1, 2]})
        result = RealDataQualityService().execute(
            dq_config(checks=[{"name": "credit_score", "type": "null_rate", "threshold": 0.99}])
        )
        detail = result["dataQualityDetails"]["credit_score"]
        assert detail["passed"] is False
        assert detail["observedValue"] == 1.0
        assert "not found" in detail["note"]

    def test_row_count_delta_vs_previous_run(self, s3):
        put_output(s3, {"prediction": [0.1] * 80})
        result = RealDataQualityService().execute(
            dq_config(checks=[{"name": "rows", "type": "row_count_delta", "threshold": 0.10}]),
            previous_row_count=100,
        )
        detail = result["dataQualityDetails"]["rows"]
        assert detail["observedValue"] == 0.2  # |80-100|/100
        assert detail["passed"] is False

    def test_row_count_delta_first_run_passes(self, s3):
        put_output(s3, {"prediction": [0.1, 0.2]})
        result = RealDataQualityService().execute(
            dq_config(checks=[{"name": "rows", "type": "row_count_delta", "threshold": 0.10}]),
            previous_row_count=None,
        )
        detail = result["dataQualityDetails"]["rows"]
        assert detail["observedValue"] == 0.0
        assert "first run" in detail["note"]

    def test_schema_match_against_baseline_features(self, s3):
        put_output(s3, {"credit_score": [650], "prediction": [0.1]})
        baseline = {
            "credit_score": {"bins": [0, 1], "proportions": [1.0]},
            "annual_income": {"bins": [0, 1], "proportions": [1.0]},
        }
        result = RealDataQualityService().execute(
            dq_config(checks=[{"name": "schema", "type": "schema_match", "threshold": 0.0}]),
            drift_baseline=baseline,
        )
        detail = result["dataQualityDetails"]["schema"]
        assert detail["observedValue"] == 0.5  # annual_income missing
        assert detail["passed"] is False
        assert "annual_income" in detail["note"]


class TestDrift:
    BASELINE = {
        # Uniform halves over [0, 10): edges 0/5/10, 50% mass in each bucket.
        "credit_score": {"bins": [0, 5, 10], "proportions": [0.5, 0.5]}
    }

    def test_matching_distribution_yields_near_zero_psi(self, s3):
        put_output(s3, {"credit_score": [1, 2, 3, 4] + [6, 7, 8, 9]})
        result = RealDataQualityService().execute(dq_config(), drift_baseline=self.BASELINE)
        assert result["driftComputation"] == "psi_vs_baseline"
        assert result["driftMetrics"]["credit_score"] < 0.01

    def test_shifted_distribution_yields_failing_psi(self, s3):
        put_output(s3, {"credit_score": [6, 7, 8, 9, 6, 7, 8, 9]})  # all upper bucket
        result = RealDataQualityService().execute(dq_config(), drift_baseline=self.BASELINE)
        assert result["driftMetrics"]["credit_score"] > 0.25

    def test_outliers_clamp_into_boundary_buckets(self, s3):
        put_output(s3, {"credit_score": [-100, -50, 999, 888]})  # 50/50 after clamping
        result = RealDataQualityService().execute(dq_config(), drift_baseline=self.BASELINE)
        assert result["driftMetrics"]["credit_score"] < 0.01

    def test_feature_missing_from_output_is_skipped_not_guessed(self, s3):
        put_output(s3, {"other": [1, 2]})
        result = RealDataQualityService().execute(dq_config(), drift_baseline=self.BASELINE)
        assert result["driftMetrics"] == {}
        assert result["driftSkippedFeatures"] == ["credit_score"]

    def test_no_baseline_reports_no_drift_evidence(self, s3):
        put_output(s3, {"credit_score": [1, 2]})
        result = RealDataQualityService().execute(dq_config(), drift_baseline=None)
        assert result["driftMetrics"] == {}
        assert result["driftComputation"] == "none"
