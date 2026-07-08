import { useState } from 'react';
import { Button, Modal } from './ui';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  /** When set, requires a non-empty comment before confirming (e.g. reject-step). */
  requireComment?: boolean;
  commentLabel?: string;
  onConfirm: (comment?: string) => void | Promise<void>;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  danger = false,
  requireComment = false,
  commentLabel = 'Comment',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const disabled = requireComment && comment.trim().length === 0;

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      await onConfirm(requireComment ? comment.trim() : undefined);
      setComment('');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onCancel} title={title} width="max-w-md">
      <p className="mb-4 text-sm text-truist-charcoal">{description}</p>
      {requireComment && (
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={commentLabel}
          className="mb-4 w-full rounded-md border border-truist-lightGray px-3 py-2 text-sm focus:border-truist-purple focus:outline-none focus:ring-2 focus:ring-truist-skyBlue"
          rows={3}
        />
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={submitting}>
          {cancelLabel}
        </Button>
        <Button
          variant={danger ? 'danger' : 'primary'}
          onClick={handleConfirm}
          disabled={disabled || submitting}
        >
          {submitting ? 'Working…' : confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
