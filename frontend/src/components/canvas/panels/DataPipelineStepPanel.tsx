import type { DataPipelineConfig } from '@/types/platform';
import { Field, Input } from '@/components/shared/ui';

export function DataPipelineStepPanel({
  config,
  onChange,
}: {
  config: DataPipelineConfig;
  onChange: (config: DataPipelineConfig) => void;
}) {
  const update = (patch: Partial<DataPipelineConfig>) => onChange({ ...config, ...patch });

  return (
    <div>
      <p className="mb-4 text-sm text-truist-darkGray">
        Extracts data from Snowflake and lands it in S3 for the downstream model execution step.
      </p>
      <div className="grid grid-cols-2 gap-x-4">
        <Field label="Snowflake database" required>
          <Input
            value={config.snowflakeDatabase}
            onChange={(e) => update({ snowflakeDatabase: e.target.value })}
            placeholder="ANALYTICS_DB"
          />
        </Field>
        <Field label="Snowflake schema" required>
          <Input
            value={config.snowflakeSchema}
            onChange={(e) => update({ snowflakeSchema: e.target.value })}
            placeholder="RISK"
          />
        </Field>
        <Field label="Snowflake table" required>
          <Input
            value={config.snowflakeTable}
            onChange={(e) => update({ snowflakeTable: e.target.value })}
            placeholder="CUSTOMER_FEATURES"
          />
        </Field>
        <Field label="Snowflake warehouse" required>
          <Input
            value={config.snowflakeWarehouse}
            onChange={(e) => update({ snowflakeWarehouse: e.target.value })}
            placeholder="COMPUTE_WH"
          />
        </Field>
      </div>
      <Field label="Destination S3 URI" required hint="Where the extracted dataset is written for the execute-model step to consume.">
        <Input
          value={config.destinationS3Uri}
          onChange={(e) => update({ destinationS3Uri: e.target.value })}
          placeholder="s3://tms-data/pipelines/staging/"
        />
      </Field>
    </div>
  );
}
