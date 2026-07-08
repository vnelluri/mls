"""
Data pipeline step execution -- mock/real split selected by SNOWFLAKE_MODE.

MockDataPipelineService is pure synthetic: no sleep (unlike the EMR mock,
this step should be instantaneous so the UI doesn't need a visible
pending/running state for it), no moto, no real Snowflake connection.
"""
import abc
import random

from app.config import settings


class DataPipelineService(abc.ABC):
    @abc.abstractmethod
    def execute(self, step_config: dict) -> dict:
        ...


class MockDataPipelineService(DataPipelineService):
    def execute(self, step_config: dict) -> dict:
        rows_written = random.randint(1000, 50000)
        return {
            "rowsWritten": rows_written,
            "s3Uri": step_config["destinationS3Uri"],
        }


class RealDataPipelineService(DataPipelineService):
    def execute(self, step_config: dict) -> dict:
        raise NotImplementedError(
            "RealDataPipelineService (live Snowflake -> S3 extraction) is out of scope for v1. "
            "Set SNOWFLAKE_MODE=mock to use the in-process simulation."
        )


def get_data_pipeline_service() -> DataPipelineService:
    if settings.SNOWFLAKE_MODE == "real":
        return RealDataPipelineService()
    return MockDataPipelineService()
