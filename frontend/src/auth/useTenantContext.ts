import { useAuth } from './AuthContext';
import type { Role } from '@/types/platform';

export interface TenantContext {
  role: Role | null;
  tenantId: string | null;
  isPlatformAdmin: boolean;
  isOperator: boolean;
  isLeadDataScientist: boolean;
  isDataScientist: boolean;
  /** PlatformAdmin and Operator span all tenants (tenantId is null). */
  seesAllTenants: boolean;
  /** Every tenant-scoped mutating control in the app must read these flags —
   * never re-derive role logic locally in a page component. PlatformAdmin is
   * deliberately excluded from every `can*` flag below: it has `tenantId:
   * null` by design (it spans all tenants), and a tenant-scoped action
   * handler that merely does `if (!tenantId) return;` would silently no-op
   * for a Platform Admin with zero visible feedback. Gate the CONTROL
   * (hide/disable + explain), don't rely on the handler to reject it. */
  canSubmitJob: boolean;
  canApproveStep: boolean;
  canRegisterModel: boolean;
  canPromoteModel: boolean;
  canManageTenants: boolean;
  /** Stop/restart/resume STAGING runs: the tenant's own scientists (Lead or
   * not) plus the cross-tenant Operator. */
  canOperateStagingJobs: boolean;
  /** Stop/rerun PRODUCTION runs: Operator only — production runs are
   * scheduler (ESP) territory; scientists don't operate them directly. */
  canOperateProductionJobs: boolean;
  /** Override a failed step so the run proceeds: LeadDataScientist — their
   * production-run lever (instead of stop/rerun). */
  canOverrideFailedStep: boolean;
}

export function useTenantContext(): TenantContext {
  const { user } = useAuth();
  const role = user?.role ?? null;
  const tenantId = user?.tenantId ?? null;

  const isPlatformAdmin = role === 'PlatformAdmin';
  const isOperator = role === 'Operator';
  const isLeadDataScientist = role === 'LeadDataScientist';
  const isDataScientist = role === 'DataScientist';

  return {
    role,
    tenantId,
    isPlatformAdmin,
    isOperator,
    isLeadDataScientist,
    isDataScientist,
    seesAllTenants: isPlatformAdmin || isOperator,
    canSubmitJob: isLeadDataScientist,
    canApproveStep: isLeadDataScientist,
    canRegisterModel: isLeadDataScientist,
    canPromoteModel: isLeadDataScientist,
    canManageTenants: isPlatformAdmin,
    canOperateStagingJobs: isDataScientist || isLeadDataScientist || isOperator,
    canOperateProductionJobs: isOperator,
    canOverrideFailedStep: isLeadDataScientist,
  };
}
