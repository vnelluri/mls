"""
Reference batch-scoring entrypoint for EMR Serverless.

This file IS the execute_model contract. The platform submits every
execute_model step as a Spark job run with this script as the entryPoint
(resolved from the tenant's execution config or EMR_ENTRYPOINT_S3_URI) and
exactly these positional arguments — see
app/services/emr_execution_service.py::RealEmrExecutionService.start:

    spark-submit scoring_entrypoint.py \
        <model-name> <model-version> <artifact-s3-uri> <input-s3-uri> <output-s3-uri>

    model-name / model-version   registry identity, for logging & lineage only
    artifact-s3-uri              the registered model's artifactS3Uri
    input-s3-uri                 run-scoped parquet prefix written by the
                                 data_pipeline step's Snowflake unload
    output-s3-uri                run-scoped prefix THIS run must write to
                                 (<outputS3Uri>/<date>/<runId>/ — never shared
                                 between runs; the platform records it as the
                                 step's resultsS3Prefix and points the
                                 data_quality_check step at it)

Output contract (what the DQ engine downstream expects):
  * parquet files under output-s3-uri;
  * every input column preserved (schema_match / null_rate checks measure
    them), plus one prediction column — name it whatever the pipeline's DQ
    step declares as `predictionColumn` ("prediction" here);
  * a row the model could not score keeps its row with a NULL prediction
    (the DQ engine's errorRate is the prediction column's null fraction) —
    the job must NOT drop unscorable rows or fail on them.

Reference implementation notes:
  * Loads a pickled model exposing scikit-learn-style `predict(DataFrame)`.
    A `.tar.gz` artifact is extracted and searched for `model.pkl`; anything
    else is treated as a raw pickle. Swap `load_model` / `score_partition`
    for your framework (XGBoost native, MLflow pyfunc, ONNX, ...) — the
    argument and output contracts above are what the platform relies on;
    how the model scores rows is yours.
  * Non-stdlib dependencies beyond pyspark/boto3 (both provided by EMR
    Serverless) must be shipped by your image or --archives virtualenv.
  * Exit non-zero on any failure: EMR surfaces it as a FAILED job run, which
    fails the platform step with the state detail.
"""
import io
import logging
import pickle
import sys
import tarfile
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scoring_entrypoint")

PREDICTION_COLUMN = "prediction"


def fetch_artifact(artifact_s3_uri: str) -> bytes:
    """Download the model artifact and return the raw pickle bytes.
    `.tar.gz` archives are searched for a `model.pkl` member."""
    import boto3

    parsed = urlparse(artifact_s3_uri)
    bucket, key = parsed.netloc, parsed.path.lstrip("/")
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()

    if key.endswith((".tar.gz", ".tgz")):
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
            member = next(
                (m for m in archive.getmembers() if m.name.endswith("model.pkl")), None
            )
            if member is None:
                raise FileNotFoundError(
                    f"{artifact_s3_uri} contains no model.pkl — archive members: "
                    f"{[m.name for m in archive.getmembers()][:20]}"
                )
            return archive.extractfile(member).read()
    return body


def main(argv: list) -> int:
    if len(argv) != 5:
        logger.error(
            "expected 5 arguments: model-name model-version artifact-s3-uri "
            "input-s3-uri output-s3-uri (got %d: %s)", len(argv), argv,
        )
        return 2
    model_name, model_version, artifact_s3_uri, input_s3_uri, output_s3_uri = argv
    logger.info(
        "scoring model=%s v%s artifact=%s input=%s output=%s",
        model_name, model_version, artifact_s3_uri, input_s3_uri, output_s3_uri,
    )

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    spark = SparkSession.builder.appName(f"score-{model_name}-v{model_version}").getOrCreate()
    try:
        model_bytes = fetch_artifact(artifact_s3_uri)
        broadcast_model = spark.sparkContext.broadcast(model_bytes)

        df = spark.read.parquet(input_s3_uri)
        input_count = df.count()
        logger.info("read %d rows from %s", input_count, input_s3_uri)

        feature_columns = df.columns
        output_schema = T.StructType(
            df.schema.fields + [T.StructField(PREDICTION_COLUMN, T.DoubleType(), True)]
        )

        def score_partition(batches):
            """Runs on executors: unpickle once per partition, score each
            Arrow batch. Unscorable rows keep a NULL prediction — errorRate
            evidence, not a crash."""
            import pandas as pd  # noqa: F401 (EMR provides pandas with pyarrow)

            model = pickle.loads(broadcast_model.value)
            for batch in batches:
                features = batch[feature_columns]
                try:
                    batch[PREDICTION_COLUMN] = model.predict(features)
                except Exception:  # scoring failure -> null predictions
                    logger.exception("partition batch failed to score (%d rows)", len(batch))
                    batch[PREDICTION_COLUMN] = None
                yield batch

        scored = df.mapInPandas(score_partition, schema=output_schema)
        scored.write.mode("overwrite").parquet(output_s3_uri)

        written = spark.read.parquet(output_s3_uri)
        written_count = written.count()
        null_predictions = written.filter(F.col(PREDICTION_COLUMN).isNull()).count()
        logger.info(
            "wrote %d rows to %s (%d null predictions)",
            written_count, output_s3_uri, null_predictions,
        )
        if written_count != input_count:
            logger.error(
                "row-count mismatch: read %d, wrote %d — output contract violated",
                input_count, written_count,
            )
            return 1
        return 0
    finally:
        spark.stop()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
