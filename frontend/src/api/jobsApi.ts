import { apiClient } from './client';
import type { Job, Paginated } from '@/types/platform';

export interface ListJobsParams {
  page?: number;
  pageSize?: number;
  status?: string;
  pipelineId?: string;
}

export async function listJobs(params: ListJobsParams = {}): Promise<Paginated<Job>> {
  const res = await apiClient.get<Paginated<Job>>('/jobs', { params });
  return res.data;
}

/** tenantId is required for cross-tenant viewers (PlatformAdmin / Operator),
 * whose own identity carries no tenant — the backend needs it to locate the
 * job. Tenant-scoped callers can omit it. */
export async function getJob(jobId: string, tenantId?: string): Promise<Job> {
  const res = await apiClient.get<Job>(`/jobs/${jobId}`, {
    params: tenantId ? { tenantId } : undefined,
  });
  return res.data;
}

export interface SubmitJobInput {
  pipelineId: string;
}

export async function submitJob(input: SubmitJobInput): Promise<Job> {
  const res = await apiClient.post<Job>('/jobs', input);
  return res.data;
}

/** Start a newly created (pending) job — jobs no longer run on creation. */
export async function startJob(jobId: string, tenantId?: string): Promise<Job> {
  const res = await apiClient.post<Job>(`/jobs/${jobId}/start`, undefined, {
    params: tenantId ? { tenantId } : undefined,
  });
  return res.data;
}

export async function stopJob(jobId: string, tenantId?: string): Promise<Job> {
  const res = await apiClient.post<Job>(`/jobs/${jobId}/stop`, undefined, {
    params: tenantId ? { tenantId } : undefined,
  });
  return res.data;
}

export async function retryJob(jobId: string, tenantId?: string): Promise<Job> {
  const res = await apiClient.post<Job>(`/jobs/${jobId}/retry`, undefined, {
    params: tenantId ? { tenantId } : undefined,
  });
  return res.data;
}

/** Continue a failed/cancelled job: completed steps keep their results, the
 * rest re-run. Contrast with retryJob, which restarts the whole run. */
export async function resumeJob(jobId: string, tenantId?: string): Promise<Job> {
  const res = await apiClient.post<Job>(`/jobs/${jobId}/resume`, undefined, {
    params: tenantId ? { tenantId } : undefined,
  });
  return res.data;
}

/** Lead Data Scientist marks a failed step as succeeded (audited) so the run
 * can proceed — the production-run escape hatch. */
export async function overrideStep(jobId: string, stepId: string): Promise<Job> {
  const res = await apiClient.post<Job>(`/jobs/${jobId}/steps/${stepId}/override`);
  return res.data;
}

export async function approveStep(jobId: string, stepId: string, comment?: string): Promise<Job> {
  const res = await apiClient.post<Job>(`/jobs/${jobId}/steps/${stepId}/approve`, { comment });
  return res.data;
}

export async function rejectStep(jobId: string, stepId: string, comment: string): Promise<Job> {
  const res = await apiClient.post<Job>(`/jobs/${jobId}/steps/${stepId}/reject`, { comment });
  return res.data;
}
