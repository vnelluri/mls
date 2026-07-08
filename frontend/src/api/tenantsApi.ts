import { apiClient } from './client';
import type { Paginated, Tenant } from '@/types/platform';

export interface ListTenantsParams {
  page?: number;
  pageSize?: number;
}

export async function listTenants(params: ListTenantsParams = {}): Promise<Paginated<Tenant>> {
  const res = await apiClient.get<Paginated<Tenant>>('/tenants', { params });
  return res.data;
}

export interface CreateTenantInput {
  name: string;
}

export async function createTenant(input: CreateTenantInput): Promise<Tenant> {
  const res = await apiClient.post<Tenant>('/tenants', input);
  return res.data;
}

export async function suspendTenant(tenantId: string): Promise<Tenant> {
  const res = await apiClient.patch<Tenant>(`/tenants/${tenantId}/suspend`);
  return res.data;
}

export async function reactivateTenant(tenantId: string): Promise<Tenant> {
  const res = await apiClient.patch<Tenant>(`/tenants/${tenantId}/reactivate`);
  return res.data;
}
