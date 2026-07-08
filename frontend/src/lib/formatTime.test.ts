import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { formatRelativeTime } from './formatTime';

describe('formatRelativeTime', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-15T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders "now" for the current instant', () => {
    expect(formatRelativeTime('2026-01-15T12:00:00Z')).toBe('now');
  });

  it('picks the largest fitting unit, past and future', () => {
    expect(formatRelativeTime('2026-01-15T11:59:30Z')).toBe('30 seconds ago');
    expect(formatRelativeTime('2026-01-15T11:55:00Z')).toBe('5 minutes ago');
    expect(formatRelativeTime('2026-01-15T09:00:00Z')).toBe('3 hours ago');
    expect(formatRelativeTime('2026-01-12T12:00:00Z')).toBe('3 days ago');
    expect(formatRelativeTime('2026-01-15T14:00:00Z')).toBe('in 2 hours');
  });

  it('rolls days into weeks and months', () => {
    expect(formatRelativeTime('2026-01-01T12:00:00Z')).toBe('2 weeks ago');
    expect(formatRelativeTime('2025-11-15T12:00:00Z')).toBe('2 months ago');
  });
});
