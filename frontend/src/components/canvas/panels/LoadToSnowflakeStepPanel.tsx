import { useState } from 'react';
import type { LoadToSnowflakeConfig } from '@/types/platform';
import { Field, InlineAlert, Textarea } from '@/components/shared/ui';

export function LoadToSnowflakeStepPanel({
  config,
  onChange,
}: {
  config: LoadToSnowflakeConfig;
  onChange: (config: LoadToSnowflakeConfig) => void;
}) {
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
      onChange({ ...config, snowflakeParams: parsed });
    } catch (err) {
      setParamsError(err instanceof Error ? err.message : 'Invalid JSON');
    }
  };

  return (
    <div>
      <p className="mb-4 text-sm text-truist-darkGray">
        Loads this run's scored output back into Snowflake — always the pipeline's <strong>last</strong> step, so it
        only runs once the run has cleared the quality gate and, if present, the approval gate. Nothing unreviewed is
        ever published. Each run <strong>appends</strong> its rows to the destination table; nothing is overwritten.
        The source is always this run's own execute-model output — there's nothing to configure for it.
      </p>
      <Field
        label="Snowflake parameters (JSON)"
        required
        hint="Must include database, schema, table, and warehouse — these build the COPY INTO load. Extra keys are accepted and unused."
      >
        <Textarea
          value={paramsText}
          onChange={(e) => handleParamsChange(e.target.value)}
          rows={6}
          spellCheck={false}
          className="font-mono text-xs"
          placeholder={
            '{\n  "database": "ANALYTICS_DB",\n  "schema": "RISK",\n  "table": "SCORED_PREDICTIONS",\n  "warehouse": "COMPUTE_WH"\n}'
          }
        />
      </Field>
      {paramsError && (
        <div className="-mt-2 mb-3">
          <InlineAlert kind="error">Invalid JSON — {paramsError}</InlineAlert>
        </div>
      )}
      <InlineAlert kind="info">
        The destination table's columns are matched by name against the scored output — make sure it has a column
        for every feature the execute-model step preserves plus its prediction column.
      </InlineAlert>
      <div className="mt-2">
        <InlineAlert kind="warning">
          The destination table must also have two extra columns for the platform to stamp on every loaded row:{' '}
          <code>_TMS_RUN_ID</code> (VARCHAR) and <code>_TMS_LOAD_DATE</code> (DATE). A missing column fails the load
          with a clear error rather than silently dropping the lineage data.
        </InlineAlert>
      </div>
    </div>
  );
}
