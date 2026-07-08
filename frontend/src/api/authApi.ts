import { apiClient } from './client';
import type { CurrentUser } from '@/types/platform';

export async function getCurrentUser(): Promise<CurrentUser> {
  const res = await apiClient.get<CurrentUser>('/auth/me');
  return res.data;
}

export async function getHealth(): Promise<{ status: string }> {
  const res = await apiClient.get<{ status: string }>('/health');
  return res.data;
}
