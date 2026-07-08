import { apiClient } from './client';
import type { MonitoringDashboard, MonitoringSnapshot, Paginated } from '@/types/platform';

export interface ListSnapshotsParams {
  // Both filters are optional server-side; omit them to list every snapshot
  // (the Monitoring page derives its model selector from the full list).
  modelName?: string;
  version?: number;
  page?: number;
  pageSize?: number;
}

export async function listMonitoringSnapshots(
  params: ListSnapshotsParams,
): Promise<Paginated<MonitoringSnapshot>> {
  const res = await apiClient.get<Paginated<MonitoringSnapshot>>('/monitoring/snapshots', {
    params,
  });
  return res.data;
}

export async function getMonitoringDashboard(): Promise<MonitoringDashboard> {
  const res = await apiClient.get<MonitoringDashboard>('/monitoring/dashboard');
  return res.data;
}
