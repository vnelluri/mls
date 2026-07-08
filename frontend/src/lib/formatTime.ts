const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 31536000],
  ['month', 2592000],
  ['week', 604800],
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
];

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

/** "5m ago" / "in 2h" — pair with the absolute datetime (e.g. as a title attribute) so exact time is one hover away. */
export function formatRelativeTime(iso: string): string {
  const diffSec = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const absSec = Math.abs(diffSec);
  for (const [unit, secInUnit] of UNITS) {
    if (absSec >= secInUnit || unit === 'second') {
      return rtf.format(Math.round(diffSec / secInUnit), unit);
    }
  }
  return rtf.format(diffSec, 'second');
}
