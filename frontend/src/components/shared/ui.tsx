import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------
type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md';
}

const buttonVariantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-truist-purple text-white hover:bg-truist-dusk disabled:bg-truist-midGray',
  secondary:
    'bg-white text-truist-purple border border-truist-purple hover:bg-truist-tint07 disabled:text-truist-midGray disabled:border-truist-midGray',
  danger: 'bg-[color:var(--status-failed)] text-white hover:opacity-90 disabled:bg-truist-midGray',
  ghost: 'bg-transparent text-truist-purple hover:bg-truist-tint07 disabled:text-truist-midGray',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', className = '', disabled, ...props }, ref) => {
    const sizeClasses = size === 'sm' ? 'px-3 py-1.5 text-sm' : 'px-4 py-2 text-sm';
    return (
      <button
        ref={ref}
        disabled={disabled}
        className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-truist-purple focus-visible:ring-offset-1 disabled:cursor-not-allowed ${sizeClasses} ${buttonVariantClasses[variant]} ${className}`}
        {...props}
      />
    );
  },
);
Button.displayName = 'Button';

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-truist-gray06 bg-white p-5 ${className}`}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field / Input / Select / Textarea
// ---------------------------------------------------------------------------
export function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="mb-3 block">
      <span className="mb-1 block text-sm font-medium text-truist-charcoal">
        {label}
        {required && <span className="ml-0.5 text-[color:var(--status-failed)]">*</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-xs text-truist-darkGray">{hint}</span>}
    </label>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className = '', ...props }, ref) => (
    <input
      ref={ref}
      className={`w-full rounded-lg border border-truist-lightGray px-3 py-2 text-sm text-truist-charcoal focus:border-truist-purple focus:outline-none focus:ring-2 focus:ring-truist-skyBlue disabled:bg-truist-gray07 disabled:text-truist-midGray ${className}`}
      {...props}
    />
  ),
);
Input.displayName = 'Input';

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className = '', children, ...props }, ref) => (
    <select
      ref={ref}
      className={`w-full rounded-lg border border-truist-lightGray bg-white px-3 py-2 text-sm text-truist-charcoal focus:border-truist-purple focus:outline-none focus:ring-2 focus:ring-truist-skyBlue disabled:bg-truist-gray07 disabled:text-truist-midGray ${className}`}
      {...props}
    >
      {children}
    </select>
  ),
);
Select.displayName = 'Select';

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className = '', ...props }, ref) => (
    <textarea
      ref={ref}
      className={`w-full rounded-lg border border-truist-lightGray px-3 py-2 text-sm text-truist-charcoal focus:border-truist-purple focus:outline-none focus:ring-2 focus:ring-truist-skyBlue disabled:bg-truist-gray07 disabled:text-truist-midGray ${className}`}
      {...props}
    />
  ),
);
Textarea.displayName = 'Textarea';

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------
export function Modal({
  open,
  onClose,
  title,
  children,
  width = 'max-w-lg',
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  width?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className={`w-full ${width} max-h-[90vh] overflow-y-auto rounded-xl border border-truist-gray06 bg-white p-6 shadow-2xl`}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-truist-charcoal">{title}</h2>
          <button
            aria-label="Close"
            onClick={onClose}
            className="rounded-lg p-1 text-truist-darkGray transition hover:bg-truist-tint07 hover:text-truist-charcoal"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// InlineAlert
// ---------------------------------------------------------------------------
type AlertKind = 'info' | 'error' | 'success' | 'warning';

const alertClasses: Record<AlertKind, string> = {
  info: 'bg-truist-tint07 text-truist-purple border-truist-dawn',
  error: 'bg-red-50 text-[color:var(--status-failed)] border-[color:var(--status-failed)]',
  success: 'bg-green-50 text-[color:var(--status-passed)] border-[color:var(--status-passed)]',
  warning: 'bg-orange-50 text-[color:var(--status-rework)] border-[color:var(--status-rework)]',
};

export function InlineAlert({ kind = 'info', children }: { kind?: AlertKind; children: ReactNode }) {
  return (
    <div className={`rounded-md border px-3 py-2 text-sm ${alertClasses[kind]}`} role="alert">
      {children}
    </div>
  );
}
