import { apiClient } from './client';
import type { DashboardSummary } from '@/types/platform';

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const res = await apiClient.get<DashboardSummary>('/dashboard/summary');
  return res.data;
}
