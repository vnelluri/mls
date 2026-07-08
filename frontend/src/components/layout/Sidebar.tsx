import { NavLink } from 'react-router-dom';
import { useTenantContext } from '@/auth/useTenantContext';

interface NavItem {
  to: string;
  label: string;
  adminOnly?: boolean;
}

const navItems: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/models', label: 'Model Registry' },
  { to: '/monitoring', label: 'Monitoring' },
  { to: '/audit', label: 'Audit Log' },
];

// Operator is a job-operations role: only the pages its API access covers
// (dashboard, jobs, monitoring) — models/audit would just 403.
const operatorNavPaths = new Set(['/dashboard', '/jobs', '/monitoring']);

const adminNavItems: NavItem[] = [
  { to: '/admin', label: 'Admin Dashboard' },
  { to: '/admin/tenants', label: 'Tenants' },
  { to: '/admin/group-mappings', label: 'Group Mappings' },
];

function linkClasses({ isActive }: { isActive: boolean }): string {
  return `block rounded-md px-3 py-2 text-sm font-medium transition-colors ${
    isActive
      ? 'bg-truist-purple text-white'
      : 'text-truist-tint07 hover:bg-truist-dusk hover:text-white'
  }`;
}

export function Sidebar() {
  const { isPlatformAdmin, isOperator } = useTenantContext();
  const visibleNavItems = isOperator
    ? navItems.filter((item) => operatorNavPaths.has(item.to))
    : navItems;

  return (
    <nav className="flex h-full w-56 shrink-0 flex-col gap-1 bg-truist-purple px-3 py-4">
      <div className="mb-4 px-2 text-lg font-semibold text-white">ML Serving Platform</div>
      {isPlatformAdmin ? (
        <>
          {adminNavItems.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === '/admin'} className={linkClasses}>
              {item.label}
            </NavLink>
          ))}
          <div className="my-3 border-t border-truist-dusk" />
        </>
      ) : null}
      {visibleNavItems.map((item) => (
        <NavLink key={item.to} to={item.to} className={linkClasses}>
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
