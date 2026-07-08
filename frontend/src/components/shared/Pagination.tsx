import type { Paginated } from '@/types/platform';
import { Button } from './ui';

export function Pagination<T>({
  data,
  onPageChange,
}: {
  data: Pick<Paginated<T>, 'total' | 'page' | 'pageSize'>;
  onPageChange: (page: number) => void;
}) {
  const { total, page, pageSize } = data;
  const pageCount = Math.max(1, Math.ceil(total / Math.max(pageSize, 1)));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  if (total === 0) return null;

  return (
    <div className="mt-4 flex items-center justify-between text-sm text-truist-darkGray">
      <span>
        Showing {start}-{end} of {total}
      </span>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          Previous
        </Button>
        <span className="px-2 py-1">
          Page {page} of {pageCount}
        </span>
        <Button
          variant="secondary"
          size="sm"
          disabled={page >= pageCount}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
