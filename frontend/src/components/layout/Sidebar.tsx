import { NavLink } from 'react-router-dom';
import { useTenantContext } from '@/auth/useTenantContext';
import { StrokeIcon } from '@/components/shared/ui';

interface NavItem {
  to: string;
  label: string;
  icon: JSX.Element;
}

const icon = (d: string) => <StrokeIcon d={d} />;

// Same 18px / 1.75-stroke icon language as TMT's sidebar.
const ICONS = {
  dashboard: icon('M4 13h6V4H4v9zm0 7h6v-5H4v5zm10 0h6V11h-6v9zm0-16v5h6V4h-6z'),
  jobs: icon('M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83'),
  models: icon('M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4'),
  monitoring: icon('M22 12h-4l-3 9L9 3l-3 9H2'),
  audit: icon('M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z'),
  admin: icon('M12 2L4 6v6c0 5.25 3.4 9.74 8 11 4.6-1.26 8-5.75 8-11V6l-8-4z'),
  tenants: icon('M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6M9 9h.01M15 9h.01M9 12h.01M15 12h.01'),
  groups: icon('M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z'),
};

const navItems: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: ICONS.dashboard },
  { to: '/jobs', label: 'Jobs', icon: ICONS.jobs },
  { to: '/models', label: 'Model Registry', icon: ICONS.models },
  { to: '/monitoring', label: 'Monitoring', icon: ICONS.monitoring },
  { to: '/audit', label: 'Audit Log', icon: ICONS.audit },
];

// Operator is a job-operations role: only the pages its API access covers
// (dashboard, jobs, monitoring) — models/audit would just 403.
const operatorNavPaths = new Set(['/dashboard', '/jobs', '/monitoring']);

const adminNavItems: NavItem[] = [
  { to: '/admin', label: 'Admin Dashboard', icon: ICONS.admin },
  { to: '/admin/tenants', label: 'Tenants', icon: ICONS.tenants },
  { to: '/admin/group-mappings', label: 'Group Mappings', icon: ICONS.groups },
];

function linkClasses({ isActive }: { isActive: boolean }): string {
  return `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
    isActive
      ? 'bg-truist-purple text-white'
      : 'text-truist-darkGray hover:bg-truist-tint07 hover:text-truist-charcoal'
  }`;
}

export function Sidebar() {
  const { isPlatformAdmin, isOperator } = useTenantContext();
  const visibleNavItems = isOperator
    ? navItems.filter((item) => operatorNavPaths.has(item.to))
    : navItems;

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-truist-gray06 bg-white">
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
        {isPlatformAdmin ? (
          <>
            {adminNavItems.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.to === '/admin'} className={linkClasses}>
                {item.icon}
                {item.label}
              </NavLink>
            ))}
            <div className="my-3 border-t border-truist-gray06" />
          </>
        ) : null}
        {visibleNavItems.map((item) => (
          <NavLink key={item.to} to={item.to} className={linkClasses}>
            {item.icon}
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
