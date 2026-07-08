import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useTenantContext } from './useTenantContext';
import type { Role } from '@/types/platform';

const mockUseAuth = vi.fn();
vi.mock('./AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}));

function contextFor(role: Role | null, tenantId: string | null = 'acme') {
  mockUseAuth.mockReturnValue({
    user: role
      ? { userId: 'u1', email: 'u@x', name: 'U', role, tenantId }
      : null,
    loading: false,
    error: null,
    demoMode: false,
    demoSelectedRole: null,
  });
  return renderHook(() => useTenantContext()).result.current;
}

describe('useTenantContext capability matrix', () => {
  it('LeadDataScientist: full tenant-scoped authority, staging ops, override', () => {
    const ctx = contextFor('LeadDataScientist');
    expect(ctx).toMatchObject({
      seesAllTenants: false,
      canSubmitJob: true,
      canApproveStep: true,
      canRegisterModel: true,
      canPromoteModel: true,
      canManageTenants: false,
      canOperateStagingJobs: true,
      canOperateProductionJobs: false,
      canOverrideFailedStep: true,
    });
  });

  it('DataScientist: staging job ops only, no other writes', () => {
    const ctx = contextFor('DataScientist');
    expect(ctx).toMatchObject({
      canSubmitJob: false,
      canApproveStep: false,
      canRegisterModel: false,
      canOperateStagingJobs: true,
      canOperateProductionJobs: false,
      canOverrideFailedStep: false,
    });
  });

  it('Operator: cross-tenant, operates staging AND production jobs, nothing else', () => {
    const ctx = contextFor('Operator', null);
    expect(ctx).toMatchObject({
      seesAllTenants: true,
      canOperateStagingJobs: true,
      canOperateProductionJobs: true,
      canSubmitJob: false,
      canApproveStep: false,
      canManageTenants: false,
    });
  });

  it('PlatformAdmin: admin console only — every tenant-scoped can* flag is false', () => {
    const ctx = contextFor('PlatformAdmin', null);
    expect(ctx.seesAllTenants).toBe(true);
    expect(ctx.canManageTenants).toBe(true);
    expect(ctx.canSubmitJob).toBe(false);
    expect(ctx.canApproveStep).toBe(false);
    expect(ctx.canRegisterModel).toBe(false);
    expect(ctx.canOperateStagingJobs).toBe(false);
    expect(ctx.canOperateProductionJobs).toBe(false);
    expect(ctx.canOverrideFailedStep).toBe(false);
  });

  it('unauthenticated: no role, no capabilities', () => {
    const ctx = contextFor(null, null);
    expect(ctx.role).toBeNull();
    expect(ctx.canSubmitJob).toBe(false);
    expect(ctx.canManageTenants).toBe(false);
  });
});
