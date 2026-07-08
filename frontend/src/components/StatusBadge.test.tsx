import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  EnvironmentBadge,
  JobStatusBadge,
  MonitoringStatusBadge,
  StatusBadge,
  StepStatusBadge,
} from './StatusBadge';

describe('status badges map every enum value to a label and palette token', () => {
  it.each([
    ['Passed', 'Passed', '--status-passed'],
    ['Failed', 'Failed', '--status-failed'],
    ['Rework', 'Rework', '--status-rework'],
    ['InReview', 'In review', '--status-in-review'],
    ['NotStarted', 'Not started', '--status-not-started'],
  ] as const)('monitoring %s', (status, label, cssVar) => {
    render(<MonitoringStatusBadge status={status} />);
    const pill = screen.getByText(label);
    expect(pill).toHaveStyle({ backgroundColor: `var(${cssVar})` });
  });

  it.each([
    ['pending', 'Pending'],
    ['running', 'Running'],
    ['awaiting_approval', 'Awaiting approval'],
    ['success', 'Success'],
    ['failed', 'Failed'],
    ['cancelled', 'Cancelled'],
  ] as const)('job %s -> "%s"', (status, label) => {
    render(<JobStatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it.each([
    ['idle', 'Idle'],
    ['succeeded', 'Succeeded'],
    ['approved', 'Approved'],
    ['rejected', 'Rejected'],
  ] as const)('step %s -> "%s"', (status, label) => {
    render(<StepStatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe('EnvironmentBadge', () => {
  it('explains the ESP-trigger rule in the hover title', () => {
    const { container } = render(<EnvironmentBadge environment="staging" />);
    expect(screen.getByText('Staging')).toBeInTheDocument();
    expect(container.querySelector('span[title]')?.getAttribute('title')).toMatch(/cannot trigger/);
  });

  it('production reads as promoted and triggerable', () => {
    const { container } = render(<EnvironmentBadge environment="production" />);
    expect(screen.getByText('Production')).toBeInTheDocument();
    expect(container.querySelector('span[title]')?.getAttribute('title')).toMatch(/ServiceNow/);
  });
});

describe('generic StatusBadge dispatches by kind', () => {
  it('routes monitoring/job/step kinds to the right meta', () => {
    render(<StatusBadge kind="monitoring" status="InReview" />);
    expect(screen.getByText('In review')).toBeInTheDocument();
    render(<StatusBadge kind="job" status="awaiting_approval" />);
    expect(screen.getByText('Awaiting approval')).toBeInTheDocument();
    render(<StatusBadge kind="step" status="succeeded" />);
    expect(screen.getByText('Succeeded')).toBeInTheDocument();
  });
});
