import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listModels, registerModel } from '@/api/modelsApi';
import type { RegisteredModel } from '@/types/platform';
import { useTenantContext } from '@/auth/useTenantContext';
import { Button, Field, InlineAlert, Input, Modal, Textarea } from '@/components/shared/ui';
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable';
import { Pagination } from '@/components/shared/Pagination';

const emptyForm = {
  modelName: '',
  modelId: '',
  version: '',
  framework: '',
  artifactS3Uri: '',
  description: '',
  driftBaselineJson: '',
};

const BASELINE_PLACEHOLDER = `{
  "credit_score": { "bins": [300, 580, 670, 740, 850], "proportions": [0.15, 0.30, 0.35, 0.20] }
}`;

/** Client-side shape check for the baseline JSON — the backend re-validates. */
function parseBaseline(raw: string): { baseline?: Record<string, { bins: number[]; proportions: number[] }>; error?: string } {
  if (!raw.trim()) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { error: 'Drift baseline is not valid JSON.' };
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { error: 'Drift baseline must be an object of feature → {bins, proportions}.' };
  }
  for (const [feature, spec] of Object.entries(parsed as Record<string, { bins?: unknown; proportions?: unknown }>)) {
    const bins = spec?.bins;
    const proportions = spec?.proportions;
    if (!Array.isArray(bins) || !Array.isArray(proportions)) {
      return { error: `Feature "${feature}" needs "bins" and "proportions" arrays.` };
    }
    if (proportions.length !== bins.length - 1) {
      return { error: `Feature "${feature}": proportions must have exactly bins.length - 1 entries.` };
    }
    const total = (proportions as number[]).reduce((a, b) => a + b, 0);
    if (total < 0.99 || total > 1.01) {
      return { error: `Feature "${feature}": proportions must sum to ~1.0 (got ${total.toFixed(4)}).` };
    }
  }
  return { baseline: parsed as Record<string, { bins: number[]; proportions: number[] }> };
}

export function ModelRegistryPage() {
  const { canRegisterModel, isPlatformAdmin } = useTenantContext();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [data, setData] = useState<{ items: RegisteredModel[]; total: number }>({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [registerOpen, setRegisterOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listModels({ page, pageSize });
      setData({ items: res.items, total: res.total });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load models.');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRegister = async () => {
    if (!canRegisterModel) {
      setSaveError('Platform Admins have view-only access across tenants — sign in as a Lead Data Scientist to register a model.');
      return;
    }
    const { baseline, error: baselineError } = parseBaseline(form.driftBaselineJson);
    if (baselineError) {
      setSaveError(baselineError);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await registerModel({
        modelName: form.modelName.trim(),
        modelId: form.modelId.trim(),
        version: form.version.trim(),
        framework: form.framework.trim(),
        artifactS3Uri: form.artifactS3Uri.trim(),
        description: form.description.trim(),
        driftBaseline: baseline,
      });
      setRegisterOpen(false);
      setForm(emptyForm);
      await load();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to register model.');
    } finally {
      setSaving(false);
    }
  };

  const columns: DataTableColumn<RegisteredModel>[] = [
    { key: 'modelName', header: 'Model', render: (m) => <span className="font-medium">{m.modelName}</span> },
    { key: 'modelId', header: 'Model ID', render: (m) => m.modelId ?? '—' },
    { key: 'version', header: 'Version', render: (m) => `v${m.version}` },
    ...(isPlatformAdmin
      ? [{ key: 'tenantId', header: 'Tenant', render: (m: RegisteredModel) => m.tenantId } as DataTableColumn<RegisteredModel>]
      : []),
    { key: 'stage', header: 'Stage', render: (m) => <span className="font-medium">{m.stage}</span> },
    { key: 'framework', header: 'Framework', render: (m) => m.framework },
    {
      key: 'registeredAt',
      header: 'Registered',
      render: (m) => new Date(m.registeredAt).toLocaleDateString(),
    },
  ];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-truist-purple">Model Registry</h1>
        {canRegisterModel ? (
          <Button onClick={() => setRegisterOpen(true)}>Register Model</Button>
        ) : (
          <span title="Platform Admins have view-only access across tenants — sign in as a Lead Data Scientist to register a model.">
            <Button disabled>Register Model</Button>
          </span>
        )}
      </div>

      {!canRegisterModel && isPlatformAdmin && (
        <div className="mb-4">
          <InlineAlert kind="info">
            Platform Admins have view-only access across tenants — sign in as a Lead Data Scientist to
            register a model.
          </InlineAlert>
        </div>
      )}

      {error && (
        <div className="mb-4">
          <InlineAlert kind="error">{error}</InlineAlert>
        </div>
      )}

      <DataTable
        columns={columns}
        rows={data.items}
        rowKey={(m) => `${m.modelName}-${m.version}`}
        loading={loading}
        emptyTitle="No models registered yet"
        onRowClick={(m) => navigate(`/models/${encodeURIComponent(m.modelName)}/${m.version}`)}
      />
      <Pagination data={{ total: data.total, page, pageSize }} onPageChange={setPage} />

      <Modal open={registerOpen} onClose={() => setRegisterOpen(false)} title="Register Model">
        {saveError && (
          <div className="mb-3">
            <InlineAlert kind="error">{saveError}</InlineAlert>
          </div>
        )}
        <Field label="Model name" required>
          <Input value={form.modelName} onChange={(e) => setForm((f) => ({ ...f, modelName: e.target.value }))} />
        </Field>
        <Field label="Model ID" required hint="Enterprise model inventory identifier (e.g. an MRM record id).">
          <Input
            value={form.modelId}
            onChange={(e) => setForm((f) => ({ ...f, modelId: e.target.value }))}
            placeholder="MDL-2026-0142"
          />
        </Field>
        <Field label="Version" required hint="Letters, digits, '.', '_' and '-' only.">
          <Input
            value={form.version}
            onChange={(e) => setForm((f) => ({ ...f, version: e.target.value }))}
            placeholder="1.0.0"
          />
        </Field>
        <Field label="Framework" required>
          <Input
            value={form.framework}
            onChange={(e) => setForm((f) => ({ ...f, framework: e.target.value }))}
            placeholder="xgboost, pytorch, sklearn…"
          />
        </Field>
        <Field
          label="Artifact S3 URI"
          required
          hint="Upload an artifact from the Dashboard to get a URI, or paste an existing one."
        >
          <Input
            value={form.artifactS3Uri}
            onChange={(e) => setForm((f) => ({ ...f, artifactS3Uri: e.target.value }))}
            placeholder="s3://tms-models/fraud-detection/v1/model.tar.gz"
          />
        </Field>
        <Field label="Description">
          <Textarea
            rows={2}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          />
        </Field>
        <Field
          label="Drift baseline (JSON)"
          hint="Optional — per-feature training-time distributions (n+1 bin edges, n proportions summing to 1). When set, scoring runs compute real PSI against it; when blank, drift numbers are synthetic."
        >
          <Textarea
            rows={4}
            className="font-mono text-xs"
            value={form.driftBaselineJson}
            onChange={(e) => setForm((f) => ({ ...f, driftBaselineJson: e.target.value }))}
            placeholder={BASELINE_PLACEHOLDER}
          />
        </Field>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setRegisterOpen(false)} disabled={saving}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleRegister()}
            disabled={
              saving ||
              !form.modelName.trim() ||
              !form.modelId.trim() ||
              !form.version.trim() ||
              !form.framework.trim() ||
              !form.artifactS3Uri.trim()
            }
          >
            {saving ? 'Registering…' : 'Register'}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
