import { apiClient } from './client';
import type { AuditEvent, Paginated } from '@/types/platform';

export interface ListAuditParams {
  page?: number;
  pageSize?: number;
  action?: string;
  entityType?: string;
}

export async function listAuditEvents(params: ListAuditParams = {}): Promise<Paginated<AuditEvent>> {
  const res = await apiClient.get<Paginated<AuditEvent>>('/audit', { params });
  return res.data;
}
