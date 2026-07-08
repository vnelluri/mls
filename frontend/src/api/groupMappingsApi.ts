import { apiClient } from './client';
import type { GroupMapping, Paginated, Role } from '@/types/platform';

export async function listGroupMappings(): Promise<Paginated<GroupMapping>> {
  const res = await apiClient.get<Paginated<GroupMapping>>('/group-mappings');
  return res.data;
}

export interface UpsertGroupMappingInput {
  mappingId?: string;
  entraGroupId: string;
  entraGroupName: string;
  role: Role;
  tenantId: string | null;
}

export async function upsertGroupMapping(input: UpsertGroupMappingInput): Promise<GroupMapping> {
  const res = await apiClient.put<GroupMapping>('/group-mappings', input);
  return res.data;
}

// Not explicitly listed in the documented contract (which only specifies
// GET/PUT), but the Group Mappings screen requires delete-behind-confirm;
// this follows the same REST shape as the other resources. Verify against
// the live backend once available.
export async function deleteGroupMapping(mappingId: string): Promise<void> {
  await apiClient.delete(`/group-mappings/${mappingId}`);
}
