// Core data model — field names must match the backend exactly (camelCase).

export type Role = 'PlatformAdmin' | 'Operator' | 'LeadDataScientist' | 'DataScientist';

export type PipelineStatus = 'draft' | 'active' | 'archived';

/** Deployment gate: pipelines are created in "staging" (manual runs only)
 * and must be promoted to "production" — with a ServiceNow ticket, recorded
 * for audit — before the external scheduler (ESP) may trigger them. */
export type PipelineEnvironment = 'staging' | 'production';

export type JobStatus =
  | 'pending'
  | 'running'
  | 'awaiting_approval'
  | 'success'
  | 'failed'
  | 'cancelled';

export type StepStatus =
  | 'idle'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'awaiting_approval'
  | 'approved'
  | 'rejected';

export type StepType =
  | 'data_pipeline'
  | 'execute_model'
  | 'data_quality_check'
  | 'approval';

export type ModelStage = 'None' | 'Staging' | 'Production' | 'Archived';

export type MonitoringStatus =
  | 'Passed'
  | 'Failed'
  | 'Rework'
  | 'InReview'
  | 'NotStarted';

export interface DataPipelineConfig {
  sourceType: 'snowflake';
  snowflakeDatabase: string;
  snowflakeSchema: string;
  snowflakeTable: string;
  snowflakeWarehouse: string;
  destinationS3Uri: string;
}

export interface ExecuteModelConfig {
  modelName: string;
  modelVersion: string;
  emrApplicationId: string;
  executionRoleArn: string;
  entryPointS3Uri: string;
  inputS3Uri: string;
  outputS3Uri: string;
  sparkSubmitParameters?: Record<string, string>;
}

export interface DataQualityCheck {
  name: string;
  type: 'null_rate' | 'row_count_delta' | 'schema_match';
  threshold: number;
}

export interface DataQualityConfig {
  checks: DataQualityCheck[];
  inputS3Uri: string;
}

export interface ApprovalConfig {
  approverNote?: string;
}

export type StepConfig =
  | DataPipelineConfig
  | ExecuteModelConfig
  | DataQualityConfig
  | ApprovalConfig;

export interface PipelineStep {
  stepId: string;
  type: StepType;
  dependsOn: string[];
  config: StepConfig;
}

export interface Pipeline {
  tenantId: string;
  pipelineId: string;
  name: string;
  description: string;
  version: number;
  status: PipelineStatus;
  requiresApproval: boolean;
  environment: PipelineEnvironment;
  promotedBy?: string | null;
  promotedAt?: string | null;
  serviceNowTicket?: string | null;
  steps: PipelineStep[];
  createdBy: string;
  createdAt: string;
  updatedBy: string;
  updatedAt: string;
}

export interface JobStepState {
  stepId: string;
  type: StepType;
  status: StepStatus;
  startedAt?: string;
  completedAt?: string;
  emrJobRunId?: string;
  emrStateDetail?: string;
  errorMessage?: string;
  output?: Record<string, unknown>;
}

export interface RunHistoryEntry {
  runId: string;
  startedAt: string;
  endedAt?: string;
  finalStatus: string;
  /** Step states as they ended (outputs, errors, EMR run ids), archived when
   * the run was retried/resumed. Only the most recent archived runs keep
   * this detail; entries from before the field existed lack it. */
  steps?: JobStepState[];
}

export interface Job {
  tenantId: string;
  jobId: string;
  pipelineId: string;
  pipelineVersion: number;
  runId: string;
  status: JobStatus;
  steps: JobStepState[];
  runHistory: RunHistoryEntry[];
  submittedBy: string;
  submittedAt: string;
  /** Set only on scheduler-triggered jobs (POST /pipelines/{id}/trigger). */
  triggeredVia?: string | null;
  externalRunId?: string | null;
  /** Snapshot of the pipeline's environment when this run started (also
   * re-snapshotted on restart/resume). */
  runEnvironment?: 'staging' | 'production' | null;
  /** The pipeline's CURRENT environment, joined by the backend at read time:
   * flips to "production" the moment the pipeline is promoted, even for jobs
   * whose runs happened in staging. */
  pipelineEnvironment?: 'staging' | 'production' | null;
  /** The pipeline's display name, joined by the backend at read time — shown
   * in place of the raw pipeline id. */
  pipelineName?: string | null;
}

/** One feature's training-time distribution: n+1 bin edges + n bucket
 * proportions (sum ≈ 1). Scoring runs compute PSI against this. */
export interface FeatureBaseline {
  bins: number[];
  proportions: number[];
}

export interface RegisteredModel {
  tenantId: string;
  modelName: string;
  /** Enterprise model inventory identifier (e.g. an MRM record id). Absent
   * on models registered before the field existed. */
  modelId?: string;
  version: string;
  stage: ModelStage;
  framework: string;
  artifactS3Uri: string;
  description: string;
  driftThresholdOverride?: number;
  errorRateThresholdOverride?: number;
  /** Per-feature training-time distributions; when present, drift is real
   * PSI against these instead of synthetic numbers. */
  driftBaseline?: Record<string, FeatureBaseline> | null;
  currentMonitoringStatus: MonitoringStatus;
  lastSnapshotAt?: string;
  registeredBy: string;
  registeredAt: string;
  promotedBy?: string;
  promotedAt?: string;
}

export interface MonitoringSnapshot {
  tenantId: string;
  modelName: string;
  version: string;
  recordedAt: string;
  jobId: string;
  runId: string;
  requestCount: number;
  avgLatencyMs: number;
  errorRate: number;
  driftMetrics: Record<string, number>;
  maxPsi: number;
  dataQualityPassed: boolean;
  derivedStatus: MonitoringStatus;
}

export interface Tenant {
  tenantId: string;
  name: string;
  status: 'active' | 'suspended';
  createdAt: string;
  createdBy: string;
}

export interface GroupMapping {
  mappingId: string;
  entraGroupId: string;
  entraGroupName: string;
  role: Role;
  tenantId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AuditEvent {
  tenantId: string;
  eventId: string;
  timestamp: string;
  actor: string;
  actorRole: Role;
  action: string;
  entityType: string;
  entityId: string;
  summary: string;
}

export interface CurrentUser {
  userId: string;
  email: string;
  name: string;
  role: Role;
  tenantId: string | null;
}

export interface MonitoringDashboard {
  counts: Record<MonitoringStatus, number>;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

// ---------------------------------------------------------------------------
// Landing dashboard (GET /dashboard/summary) — available to every role.
// Tenant-scoped roles get own-tenant numbers; PlatformAdmin gets cross-tenant
// aggregates plus tenantCount (null for everyone else).
// ---------------------------------------------------------------------------

export interface PipelineStats {
  total: number;
  byStatus: Record<PipelineStatus, number>;
}

export interface JobStats {
  total: number;
  byStatus: Record<JobStatus, number>;
}

export interface ModelStats {
  total: number;
  byStage: Record<ModelStage, number>;
  byMonitoringStatus: Record<MonitoringStatus, number>;
}

export interface DashboardSummary {
  role: Role;
  tenantId: string | null;
  tenantCount: number | null;
  pipelines: PipelineStats;
  jobs: JobStats;
  models: ModelStats;
  recentJobs: Job[];
  recentAuditEvents: AuditEvent[];
}
