import type { JobStepState, PipelineStep, StepStatus } from '@/types/platform';
import { NODE_HEIGHT, NODE_WIDTH, StepNode } from './StepNode';

const H_GAP = 64;
const PADDING = 24;

export interface CanvasStep {
  stepId: string;
  type: PipelineStep['type'];
  dependsOn: string[];
  label?: string;
  status?: StepStatus;
  startedAt?: string;
  completedAt?: string;
}

export function stepsToCanvasSteps(steps: PipelineStep[], jobSteps?: JobStepState[]): CanvasStep[] {
  return steps.map((step) => {
    const jobStep = jobSteps?.find((js) => js.stepId === step.stepId);
    return {
      stepId: step.stepId,
      type: step.type,
      dependsOn: step.dependsOn,
      status: jobStep?.status,
      startedAt: jobStep?.startedAt,
      completedAt: jobStep?.completedAt,
    };
  });
}

/**
 * SVG-based left-to-right chain of connected step nodes. v1 pipelines are
 * always linear, but this accepts a generic `steps` array with `dependsOn`
 * edges (drawing a connector between each dependency pair) so it isn't hard
 * to extend to branching layouts later — the layout algorithm below just
 * happens to place nodes in array order for now.
 */
export function PipelineCanvas({
  steps,
  selectedStepId,
  interactive = false,
  onSelectStep,
}: {
  steps: CanvasStep[];
  selectedStepId?: string | null;
  interactive?: boolean;
  onSelectStep?: (stepId: string) => void;
}) {
  const positions = new Map<string, { x: number; y: number }>();
  steps.forEach((step, i) => {
    positions.set(step.stepId, { x: PADDING + i * (NODE_WIDTH + H_GAP), y: PADDING });
  });

  const width = PADDING * 2 + steps.length * NODE_WIDTH + Math.max(0, steps.length - 1) * H_GAP;
  const height = PADDING * 2 + NODE_HEIGHT;

  const edges: { from: string; to: string }[] = [];
  steps.forEach((step) => {
    step.dependsOn.forEach((depId) => {
      if (positions.has(depId)) edges.push({ from: depId, to: step.stepId });
    });
  });

  if (steps.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-truist-lightGray bg-truist-gray07 p-8 text-center text-sm text-truist-darkGray">
        No steps yet. Add a step to start building this pipeline.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-truist-gray06 bg-truist-tint08 p-2">
      <svg width={width} height={height} role="img" aria-label="Pipeline step diagram">
        {edges.map(({ from, to }) => {
          const a = positions.get(from)!;
          const b = positions.get(to)!;
          const x1 = a.x + NODE_WIDTH - 4;
          const y1 = a.y + NODE_HEIGHT / 2;
          const x2 = b.x + 4;
          const y2 = b.y + NODE_HEIGHT / 2;
          const midX = (x1 + x2) / 2;
          return (
            <path
              key={`${from}-${to}`}
              d={`M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`}
              stroke="var(--truist-charcoal)"
              strokeWidth={2}
              fill="none"
              markerEnd="url(#pipeline-arrow)"
            />
          );
        })}
        <defs>
          <marker
            id="pipeline-arrow"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--truist-charcoal)" />
          </marker>
        </defs>
        {steps.map((step) => {
          const pos = positions.get(step.stepId)!;
          return (
            <foreignObject key={step.stepId} x={pos.x} y={pos.y} width={NODE_WIDTH} height={NODE_HEIGHT}>
              <StepNode
                type={step.type}
                label={step.label ?? step.stepId}
                status={step.status}
                startedAt={step.startedAt}
                completedAt={step.completedAt}
                selected={selectedStepId === step.stepId}
                interactive={interactive}
                onClick={() => onSelectStep?.(step.stepId)}
              />
            </foreignObject>
          );
        })}
      </svg>
    </div>
  );
}
