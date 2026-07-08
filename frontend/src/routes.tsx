import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { useTenantContext } from '@/auth/useTenantContext';
import { Layout } from '@/components/layout/Layout';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { LoginPage } from '@/pages/auth/LoginPage';
import { DashboardPage } from '@/pages/dashboard/DashboardPage';
import { AdminDashboardPage } from '@/pages/admin/AdminDashboardPage';
import { TenantsPage } from '@/pages/admin/TenantsPage';
import { GroupMappingsPage } from '@/pages/admin/GroupMappingsPage';
import { JobsListPage } from '@/pages/jobs/JobsListPage';
import { JobDetailPage } from '@/pages/jobs/JobDetailPage';
import { ModelRegistryPage } from '@/pages/models/ModelRegistryPage';
import { ModelDetailPage } from '@/pages/models/ModelDetailPage';
import { MonitoringDashboardPage } from '@/pages/monitoring/MonitoringDashboardPage';
import { AuditLogPage } from '@/pages/audit/AuditLogPage';

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <LoadingSpinner label="Checking session…" />;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

/** /admin/* is Platform-Admin-only. Every other route is shared, with
 * individual controls inside each page gated per-action via
 * useTenantContext's can* flags rather than blocking the whole route. */
function RequirePlatformAdmin({ children }: { children: JSX.Element }) {
  const { isPlatformAdmin } = useTenantContext();
  if (!isPlatformAdmin) return <Navigate to="/dashboard" replace />;
  return children;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />

        <Route
          path="/admin"
          element={
            <RequirePlatformAdmin>
              <AdminDashboardPage />
            </RequirePlatformAdmin>
          }
        />
        <Route
          path="/admin/tenants"
          element={
            <RequirePlatformAdmin>
              <TenantsPage />
            </RequirePlatformAdmin>
          }
        />
        <Route
          path="/admin/group-mappings"
          element={
            <RequirePlatformAdmin>
              <GroupMappingsPage />
            </RequirePlatformAdmin>
          }
        />

        <Route path="/jobs" element={<JobsListPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />

        <Route path="/models" element={<ModelRegistryPage />} />
        <Route path="/models/:modelName/:version" element={<ModelDetailPage />} />

        <Route path="/monitoring" element={<MonitoringDashboardPage />} />
        <Route path="/audit" element={<AuditLogPage />} />

        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
