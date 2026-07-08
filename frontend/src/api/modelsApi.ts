import { apiClient } from './client';
import type {
  FeatureBaseline,
  ModelStage,
  MonitoringStatus,
  Paginated,
  RegisteredModel,
} from '@/types/platform';

export interface ListModelsParams {
  page?: number;
  pageSize?: number;
  modelName?: string;
  stage?: ModelStage;
  // Not explicitly enumerated in the documented /models query params, but
  // required to support the Monitoring Dashboard's drill-down-by-status
  // links; follows the same filter convention as `stage`. Verify against
  // the live backend once available.
  monitoringStatus?: MonitoringStatus;
}

export async function listModels(params: ListModelsParams = {}): Promise<Paginated<RegisteredModel>> {
  const res = await apiClient.get<Paginated<RegisteredModel>>('/models', { params });
  return res.data;
}

export async function getModel(modelName: string, version: string): Promise<RegisteredModel> {
  const res = await apiClient.get<RegisteredModel>(
    `/models/${encodeURIComponent(modelName)}/${encodeURIComponent(version)}`,
  );
  return res.data;
}

export interface RegisterModelInput {
  modelName: string;
  modelId: string;
  version: string;
  framework: string;
  artifactS3Uri: string;
  description: string;
  driftThresholdOverride?: number;
  errorRateThresholdOverride?: number;
  driftBaseline?: Record<string, FeatureBaseline>;
}

export async function registerModel(input: RegisterModelInput): Promise<RegisteredModel> {
  const res = await apiClient.post<RegisteredModel>('/models', input);
  return res.data;
}

export async function promoteModel(
  modelName: string,
  version: string,
  stage: ModelStage,
): Promise<RegisteredModel> {
  const res = await apiClient.patch<RegisteredModel>(
    `/models/${encodeURIComponent(modelName)}/${encodeURIComponent(version)}/promote`,
    { targetStage: stage },
  );
  return res.data;
}
