import type { StepStatus, StepType } from '@/types/platform';

export const stepTypeLabels: Record<StepType, string> = {
  data_pipeline: 'Data Pipeline',
  execute_model: 'Execute Model',
  data_quality_check: 'Data Quality Check',
  approval: 'Approval',
};

const stepStatusVar: Record<StepStatus, string> = {
  idle: '--status-not-started',
  running: '--status-in-review',
  succeeded: '--status-passed',
  failed: '--status-failed',
  awaiting_approval: '--status-rework',
  approved: '--status-passed',
  rejected: '--status-failed',
};

export const NODE_WIDTH = 208;
export const NODE_HEIGHT = 96;

function TypeGlyph({ type }: { type: StepType }) {
  const common = { stroke: 'var(--truist-purple)', strokeWidth: 2, fill: 'none' } as const;
  switch (type) {
    case 'data_pipeline':
      return (
        <svg width="20" height="20" viewBox="0 0 20 20">
          <ellipse cx="10" cy="4" rx="7" ry="2.5" {...common} />
          <path d="M3 4v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V4" {...common} />
          <path d="M3 10c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5" {...common} />
        </svg>
      );
    case 'execute_model':
      return (
        <svg width="20" height="20" viewBox="0 0 20 20">
          <rect x="4" y="4" width="12" height="12" rx="2" {...common} />
          <path d="M7 4V2M13 4V2M7 18v-2M13 18v-2M4 7H2M4 13H2M18 7h-2M18 13h-2" {...common} />
        </svg>
      );
    case 'data_quality_check':
      return (
        <svg width="20" height="20" viewBox="0 0 20 20">
          <rect x="3" y="3" width="14" height="14" rx="2" {...common} />
          <path d="M6.5 10.5l2.2 2.2L14 8.2" {...common} />
        </svg>
      );
    case 'approval':
      return (
        <svg width="20" height="20" viewBox="0 0 20 20">
          <circle cx="10" cy="7" r="3" {...common} />
          <path d="M4 17c0-3.3 2.7-6 6-6s6 2.7 6 6" {...common} />
        </svg>
      );
    default:
      return null;
  }
}

/**
 * A single step node, rendered as a foreignObject inside the pipeline SVG so
 * ordinary HTML/Tailwind can lay out the label/timestamps text, while the
 * border/status accent still uses the raw CSS custom properties (--truist-…
 * and --status-…, required in the SVG context, since Tailwind color
 * utilities don't apply to stroke/fill there).
 */
export function StepNode({
  type,
  label,
  status,
  startedAt,
  completedAt,
  selected,
  interactive,
  onClick,
}: {
  type: StepType;
  label?: string;
  status?: StepStatus;
  startedAt?: string;
  completedAt?: string;
  selected?: boolean;
  interactive?: boolean;
  onClick?: () => void;
}) {
  const accentVar = status ? stepStatusVar[status] : null;
  const borderColor = selected ? 'var(--truist-purple)' : 'var(--truist-light-gray)';

  return (
    <div
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? onClick : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') onClick?.();
            }
          : undefined
      }
      style={{
        width: NODE_WIDTH - 8,
        height: NODE_HEIGHT - 8,
        border: `2px solid ${borderColor}`,
        borderRadius: 10,
        background: '#ffffff',
        boxShadow: selected ? '0 0 0 3px var(--truist-sky-blue)' : undefined,
      }}
      className={`flex flex-col justify-between p-3 ${
        interactive ? 'cursor-pointer hover:border-truist-dusk' : ''
      }`}
    >
      <div className="flex items-center gap-2">
        <TypeGlyph type={type} />
        <span className="text-xs font-semibold uppercase tracking-wide text-truist-purple">
          {stepTypeLabels[type]}
        </span>
      </div>
      {label && <div className="truncate text-sm font-medium text-truist-charcoal">{label}</div>}
      <div className="flex items-center justify-between">
        {accentVar ? (
          <span
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold text-white"
            style={{ backgroundColor: `var(${accentVar})` }}
          >
            {status}
          </span>
        ) : (
          <span className="text-[10px] text-truist-midGray">
            {interactive ? 'Click to configure' : ''}
          </span>
        )}
        {(startedAt || completedAt) && (
          <span className="text-[10px] text-truist-darkGray">
            {startedAt ? new Date(startedAt).toLocaleTimeString() : ''}
            {completedAt ? ` – ${new Date(completedAt).toLocaleTimeString()}` : ''}
          </span>
        )}
      </div>
    </div>
  );
}
