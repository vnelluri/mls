import { apiClient } from './client';
import type { Pipeline, PipelineStep } from '@/types/platform';

export async function getPipeline(pipelineId: string): Promise<Pipeline> {
  const res = await apiClient.get<Pipeline>(`/pipelines/${pipelineId}`);
  return res.data;
}

export interface CreatePipelineInput {
  name: string;
  description: string;
  requiresApproval: boolean;
  steps: PipelineStep[];
}

export async function createPipeline(input: CreatePipelineInput): Promise<Pipeline> {
  const res = await apiClient.post<Pipeline>('/pipelines', input);
  return res.data;
}

/** Promote a reviewed staging pipeline to production. Requires a ServiceNow
 * change ticket (e.g. CHG0031245) — recorded on the pipeline and in the audit
 * log — and at least one successful staging run. */
export async function promotePipeline(pipelineId: string, serviceNowTicket: string): Promise<Pipeline> {
  const res = await apiClient.post<Pipeline>(`/pipelines/${pipelineId}/promote`, { serviceNowTicket });
  return res.data;
}
