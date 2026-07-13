import { Outlet } from 'react-router-dom';
import { Copyright } from '@/components/shared/ui';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

// TMT layout shape: brand topbar across the top, light sidebar below it,
// centered max-width content, copyright footer.
export function Layout() {
  return (
    <div className="flex h-screen flex-col bg-truist-tint08">
      <Topbar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto px-6 py-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>
      <footer className="flex h-9 shrink-0 items-center justify-center border-t border-truist-gray06 bg-white text-xs text-truist-midGray">
        <Copyright suffix="All rights reserved." />
      </footer>
    </div>
  );
}
