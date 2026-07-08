import { useEffect, useMemo, useState } from 'react';
import type { ExecuteModelConfig, RegisteredModel } from '@/types/platform';
import { Field, Input } from '@/components/shared/ui';
import { listModels } from '@/api/modelsApi';

export function ExecuteModelStepPanel({
  config,
  onChange,
}: {
  config: ExecuteModelConfig;
  onChange: (config: ExecuteModelConfig) => void;
}) {
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [modelQuery, setModelQuery] = useState(config.modelName);
  const [showResults, setShowResults] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listModels({ pageSize: 100 })
      .then((res) => {
        if (!cancelled) setModels(res.items);
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = modelQuery.trim().toLowerCase();
    if (!q) return models.slice(0, 8);
    return models.filter((m) => m.modelName.toLowerCase().includes(q)).slice(0, 8);
  }, [models, modelQuery]);

  const update = (patch: Partial<ExecuteModelConfig>) => onChange({ ...config, ...patch });

  return (
    <div>
      <p className="mb-4 text-sm text-truist-darkGray">
        Runs the specified model version as an EMR Serverless job over the S3 dataset produced by the
        data pipeline step.
      </p>
      <div className="relative">
        <Field label="Model" required hint="Search the registry, or type a model name directly.">
          <Input
            value={modelQuery}
            onChange={(e) => {
              setModelQuery(e.target.value);
              update({ modelName: e.target.value });
              setShowResults(true);
            }}
            onFocus={() => setShowResults(true)}
            onBlur={() => setTimeout(() => setShowResults(false), 150)}
            placeholder="fraud-detection-xgb"
          />
        </Field>
        {showResults && filtered.length > 0 && (
          <ul className="absolute z-10 mb-2 max-h-48 w-full -translate-y-full overflow-y-auto rounded-md border border-truist-lightGray bg-white shadow-lg">
            {filtered.map((m) => (
              <li key={`${m.modelName}-${m.version}`}>
                <button
                  type="button"
                  className="block w-full px-3 py-1.5 text-left text-sm hover:bg-truist-tint07"
                  onMouseDown={() => {
                    setModelQuery(m.modelName);
                    update({ modelName: m.modelName, modelVersion: m.version });
                    setShowResults(false);
                  }}
                >
                  {m.modelName} <span className="text-truist-darkGray">v{m.version}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Field label="Model version" required>
        <Input
          value={config.modelVersion}
          onChange={(e) => update({ modelVersion: e.target.value })}
          placeholder="1.0.0"
        />
      </Field>
      <p className="mb-4 text-xs text-truist-darkGray">
        The EMR application, execution role, and scoring entrypoint are managed by the platform for
        your tenant — they are resolved automatically when the step runs.
      </p>
      <div className="grid grid-cols-2 gap-x-4">
        <Field label="Input S3 URI" required>
          <Input
            value={config.inputS3Uri}
            onChange={(e) => update({ inputS3Uri: e.target.value })}
            placeholder="s3://tms-data/pipelines/staging/"
          />
        </Field>
        <Field label="Output S3 URI" required>
          <Input
            value={config.outputS3Uri}
            onChange={(e) => update({ outputS3Uri: e.target.value })}
            placeholder="s3://tms-data/pipelines/scored/"
          />
        </Field>
      </div>
    </div>
  );
}
