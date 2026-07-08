import type { DataQualityCheck, DataQualityConfig } from '@/types/platform';
import { Button, Field, Input, Select } from '@/components/shared/ui';

const checkTypes: DataQualityCheck['type'][] = ['null_rate', 'row_count_delta', 'schema_match'];

const checkTypeLabels: Record<DataQualityCheck['type'], string> = {
  null_rate: 'Null rate',
  row_count_delta: 'Row count delta',
  schema_match: 'Schema match',
};

export function DataQualityStepPanel({
  config,
  onChange,
}: {
  config: DataQualityConfig;
  onChange: (config: DataQualityConfig) => void;
}) {
  const updateCheck = (index: number, patch: Partial<DataQualityCheck>) => {
    const checks = config.checks.map((c, i) => (i === index ? { ...c, ...patch } : c));
    onChange({ ...config, checks });
  };

  const addCheck = () => {
    onChange({
      ...config,
      checks: [...config.checks, { name: '', type: 'null_rate', threshold: 0.05 }],
    });
  };

  const removeCheck = (index: number) => {
    onChange({ ...config, checks: config.checks.filter((_, i) => i !== index) });
  };

  return (
    <div>
      <p className="mb-4 text-sm text-truist-darkGray">
        Validates the model output before it can proceed (to approval, if required, or completion).
        Completing this step records a monitoring snapshot for the model.
      </p>
      <Field label="Input S3 URI" required hint="Dataset this data quality step evaluates (typically the execute-model step's output).">
        <Input
          value={config.inputS3Uri}
          onChange={(e) => onChange({ ...config, inputS3Uri: e.target.value })}
          placeholder="s3://tms-data/pipelines/scored/"
        />
      </Field>

      <div className="mt-3 space-y-3">
        <span className="block text-sm font-medium text-truist-charcoal">Checks</span>
        {config.checks.length === 0 && (
          <p className="text-sm text-truist-darkGray">No checks configured yet.</p>
        )}
        {config.checks.map((check, i) => (
          <div key={i} className="flex items-end gap-2 rounded-md border border-truist-gray06 p-3">
            <Field label="Name" required>
              <Input
                value={check.name}
                onChange={(e) => updateCheck(i, { name: e.target.value })}
                placeholder="null_rate_check"
              />
            </Field>
            <Field label="Type">
              <Select
                value={check.type}
                onChange={(e) => updateCheck(i, { type: e.target.value as DataQualityCheck['type'] })}
              >
                {checkTypes.map((t) => (
                  <option key={t} value={t}>
                    {checkTypeLabels[t]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Threshold">
              <Input
                type="number"
                step="0.01"
                value={check.threshold}
                onChange={(e) => updateCheck(i, { threshold: Number(e.target.value) })}
              />
            </Field>
            <Button variant="danger" size="sm" className="mb-3" onClick={() => removeCheck(i)}>
              Remove
            </Button>
          </div>
        ))}
        <Button variant="secondary" size="sm" onClick={addCheck}>
          + Add check
        </Button>
      </div>
    </div>
  );
}
