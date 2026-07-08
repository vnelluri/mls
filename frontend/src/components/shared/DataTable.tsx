import type { ReactNode } from 'react';
import { LoadingSpinner } from './LoadingSpinner';
import { EmptyState } from './EmptyState';

export interface DataTableColumn<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  emptyTitle = 'No records found',
  emptyDescription,
  onRowClick,
  rowClassName,
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string;
}) {
  if (loading) return <LoadingSpinner />;
  if (rows.length === 0) return <EmptyState title={emptyTitle} description={emptyDescription} />;

  return (
    <div className="overflow-x-auto rounded-lg border border-truist-gray06">
      <table className="min-w-full divide-y divide-truist-gray06 text-sm">
        <thead className="bg-truist-tint08">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-truist-charcoal"
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-truist-gray06 bg-white">
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={
                onRowClick
                  ? (e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onRowClick(row);
                      }
                    }
                  : undefined
              }
              tabIndex={onRowClick ? 0 : undefined}
              role={onRowClick ? 'button' : undefined}
              className={`${
                onRowClick
                  ? 'cursor-pointer hover:bg-truist-tint08 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-truist-skyBlue'
                  : ''
              } ${rowClassName?.(row) ?? ''}`}
            >
              {columns.map((col) => (
                <td key={col.key} className={`px-4 py-2.5 text-truist-charcoal ${col.className ?? ''}`}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
