import type { ReactNode } from 'react';

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-truist-lightGray bg-truist-gray07 py-14 text-center">
      <p className="text-sm font-medium text-truist-charcoal">{title}</p>
      {description && <p className="max-w-md text-sm text-truist-darkGray">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
