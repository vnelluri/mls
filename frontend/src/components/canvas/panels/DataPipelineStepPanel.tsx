import { useState } from 'react';
import type { DataPipelineConfig } from '@/types/platform';
import { Field, InlineAlert, Input, Textarea } from '@/components/shared/ui';

export function DataPipelineStepPanel({
  config,
  onChange,
}: {
  config: DataPipelineConfig;
  onChange: (config: DataPipelineConfig) => void;
}) {
  const update = (patch: Partial<DataPipelineConfig>) => onChange({ ...config, ...patch });

  // The textarea holds free-typed JSON, which is often momentarily invalid
  // mid-edit -- only commit to config.snowflakeParams once it parses.
  const [paramsText, setParamsText] = useState(() => JSON.stringify(config.snowflakeParams ?? {}, null, 2));
  const [paramsError, setParamsError] = useState<string | null>(null);

  const handleParamsChange = (text: string) => {
    setParamsText(text);
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('must be a JSON object');
      }
      setParamsError(null);
      update({ snowflakeParams: parsed });
    } catch (err) {
      setParamsError(err instanceof Error ? err.message : 'Invalid JSON');
    }
  };

  const scripted = Boolean(config.scriptS3Uri?.trim());

  return (
    <div>
      <p className="mb-4 text-sm text-truist-darkGray">
        Extracts data from Snowflake and lands it in S3 for the downstream model execution step.
      </p>
      <Field
        label="Snowflake parameters (JSON)"
        required={!scripted}
        hint={
          scripted
            ? 'Handed to the script below verbatim, as a JSON string — its shape is entirely up to the script.'
            : 'Must include database, schema, table, and warehouse — these build the unload. Extra keys are accepted and unused.'
        }
      >
        <Textarea
          value={paramsText}
          onChange={(e) => handleParamsChange(e.target.value)}
          rows={6}
          spellCheck={false}
          className="font-mono text-xs"
          placeholder={
            '{\n  "database": "ANALYTICS_DB",\n  "schema": "RISK",\n  "table": "CUSTOMER_FEATURES",\n  "warehouse": "COMPUTE_WH"\n}'
          }
        />
      </Field>
      {paramsError && (
        <div className="-mt-2 mb-3">
          <InlineAlert kind="error">Invalid JSON — {paramsError}</InlineAlert>
        </div>
      )}
      <Field
        label="Destination S3 URI"
        required
        hint="Where the extracted dataset is written for the execute-model step to consume."
      >
        <Input
          value={config.destinationS3Uri}
          onChange={(e) => update({ destinationS3Uri: e.target.value })}
          placeholder="s3://tms-data/pipelines/staging/"
        />
      </Field>
      <Field
        label="Script S3 URI (optional)"
        hint="Set this to replace the built-in Snowflake unload with your own script (Spark, e.g. via Snowpark for Python) — it's submitted to your tenant's EMR Serverless application instead."
      >
        <Input
          value={config.scriptS3Uri ?? ''}
          onChange={(e) => update({ scriptS3Uri: e.target.value || undefined })}
          placeholder="s3://tms-data/<tenant>/scripts/extract.py"
        />
      </Field>
    </div>
  );
}
