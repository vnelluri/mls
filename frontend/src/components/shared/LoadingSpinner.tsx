export function LoadingSpinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-12 text-truist-darkGray">
      <span
        className="h-5 w-5 animate-spin rounded-full border-2 border-truist-lightGray border-t-truist-purple"
        aria-hidden="true"
      />
      <span className="text-sm">{label}</span>
    </div>
  );
}
