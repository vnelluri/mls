import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getModel, listModels, promoteModel } from '@/api/modelsApi';
import type { ModelStage, RegisteredModel } from '@/types/platform';
import { useTenantContext } from '@/auth/useTenantContext';
import { Button, Card, InlineAlert } from '@/components/shared/ui';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { MonitoringStatusBadge } from '@/components/StatusBadge';

const allStages: ModelStage[] = ['None', 'Staging', 'Production', 'Archived'];

// Legal stage transitions. Illegal targets are grayed out in the UI rather
// than letting the click hit the backend and 409.
const legalTransitions: Record<ModelStage, ModelStage[]> = {
  None: ['Staging'],
  Staging: ['Production', 'Archived'],
  Production: ['Archived'],
  Archived: [],
};

export function ModelDetailPage() {
  const { modelName, version } = useParams<{ modelName: string; version: string }>();
  const navigate = useNavigate();
  const { canPromoteModel } = useTenantContext();

  const [model, setModel] = useState<RegisteredModel | null>(null);
  const [versions, setVersions] = useState<RegisteredModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [promoteTarget, setPromoteTarget] = useState<ModelStage | null>(null);
  const [promoting, setPromoting] = useState(false);

  const load = useCallback(async () => {
    if (!modelName || !version) return;
    setLoading(true);
    setError(null);
    try {
      const [m, allVersions] = await Promise.all([
        getModel(modelName, version),
        listModels({ modelName, pageSize: 100 }),
      ]);
      setModel(m);
      setVersions(
        allVersions.items.sort((a, b) => b.version.localeCompare(a.version, undefined, { numeric: true })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load model.');
    } finally {
      setLoading(false);
    }
  }, [modelName, version]);

  useEffect(() => {
    void load();
  }, [load]);

  const handlePromote = async () => {
    if (!model || !promoteTarget) return;
    if (!canPromoteModel) {
      setActionError('Only Lead Data Scientists can promote a model stage.');
      return;
    }
    setPromoting(true);
    setActionError(null);
    try {
      const updated = await promoteModel(model.modelName, model.version, promoteTarget);
      setModel(updated);
      setPromoteTarget(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to promote model.');
    } finally {
      setPromoting(false);
    }
  };

  if (loading) return <LoadingSpinner label="Loading model…" />;
  if (error) return <InlineAlert kind="error">{error}</InlineAlert>;
  if (!model) return <InlineAlert kind="error">Model not found.</InlineAlert>;

  const legalTargets = legalTransitions[model.stage];

  return (
    <div>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-truist-purple">
            {model.modelName} <span className="text-truist-darkGray">v{model.version}</span>
          </h1>
          <p className="text-sm text-truist-darkGray">{model.description}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <MonitoringStatusBadge status={model.currentMonitoringStatus} />
          <Link
            to={`/monitoring?model=${encodeURIComponent(model.modelName)}&version=${model.version}`}
            className="text-xs text-truist-purple underline"
          >
            View drift metrics on the Monitoring page →
          </Link>
        </div>
      </div>

      {actionError && (
        <div className="mb-4">
          <InlineAlert kind="error">{actionError}</InlineAlert>
        </div>
      )}

      <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Details</h2>
          <dl className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <dt className="text-truist-darkGray">Framework</dt>
              <dd>{model.framework}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-truist-darkGray">Stage</dt>
              <dd className="font-medium">{model.stage}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-truist-darkGray">Registered by</dt>
              <dd>{model.registeredBy}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-truist-darkGray">Registered at</dt>
              <dd>{new Date(model.registeredAt).toLocaleString()}</dd>
            </div>
            {model.promotedBy && (
              <div className="flex justify-between">
                <dt className="text-truist-darkGray">Last promoted by</dt>
                <dd>
                  {model.promotedBy}
                  {model.promotedAt ? ` (${new Date(model.promotedAt).toLocaleDateString()})` : ''}
                </dd>
              </div>
            )}
            {model.modelId && (
              <div className="flex justify-between">
                <dt className="text-truist-darkGray">Model ID</dt>
                <dd>
                  <code className="text-xs">{model.modelId}</code>
                </dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-truist-darkGray">Artifact</dt>
              <dd className="max-w-[60%] truncate text-right">
                <code className="text-xs">{model.artifactS3Uri}</code>
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-truist-darkGray">Drift baseline</dt>
              <dd
                title={
                  model.driftBaseline
                    ? `PSI computed against training-time distributions of: ${Object.keys(model.driftBaseline).join(', ')}`
                    : 'No baseline registered — drift numbers are synthetic (demo mode)'
                }
              >
                {model.driftBaseline
                  ? `${Object.keys(model.driftBaseline).length} feature(s) — real PSI`
                  : 'None (synthetic drift)'}
              </dd>
            </div>
          </dl>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Promote stage</h2>
          <p className="mb-3 text-xs text-truist-darkGray">
            Current stage: <span className="font-medium text-truist-charcoal">{model.stage}</span>
          </p>
          <div className="flex flex-wrap gap-2">
            {allStages
              .filter((s) => s !== model.stage)
              .map((stage) => {
                const legal = legalTargets.includes(stage);
                const disabled = !canPromoteModel || !legal;
                return (
                  <span
                    key={stage}
                    title={
                      !canPromoteModel
                        ? "Platform Admins have view-only access across tenants — sign in as a Lead Data Scientist to promote a model."
                        : !legal
                          ? `Not a legal transition from ${model.stage}`
                          : undefined
                    }
                  >
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={disabled}
                      onClick={() => setPromoteTarget(stage)}
                    >
                      → {stage}
                    </Button>
                  </span>
                );
              })}
          </div>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Other versions</h2>
          <ul className="space-y-1.5 text-sm">
            {versions.map((v) => (
              <li key={v.version}>
                <button
                  onClick={() => navigate(`/models/${encodeURIComponent(v.modelName)}/${v.version}`)}
                  className={`flex w-full items-center justify-between rounded px-2 py-1 text-left hover:bg-truist-tint08 ${
                    v.version === model.version ? 'bg-truist-tint07 font-medium' : ''
                  }`}
                >
                  <span>v{v.version}</span>
                  <span className="text-xs text-truist-darkGray">{v.stage}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <ConfirmDialog
        open={!!promoteTarget}
        title={`Promote to ${promoteTarget ?? ''}`}
        description={`Change ${model.modelName} v${model.version} from ${model.stage} to ${promoteTarget}? This affects which deployments treat this version as current for its stage.`}
        confirmLabel="Promote"
        onConfirm={() => handlePromote()}
        onCancel={() => setPromoteTarget(null)}
      />
    </div>
  );
}
