import type { ApprovalConfig } from '@/types/platform';
import { Field, Textarea } from '@/components/shared/ui';

export function ApprovalStepPanel({
  config,
  onChange,
}: {
  config: ApprovalConfig;
  onChange: (config: ApprovalConfig) => void;
}) {
  return (
    <div>
      <p className="mb-4 text-sm text-truist-darkGray">
        A lightweight peer-review gate: a Lead Data Scientist reviews the job's progress so far and
        approves or rejects before the job continues. This is a peer check, not a formal governance
        review.
      </p>
      <Field label="Note for approvers (optional)">
        <Textarea
          rows={3}
          value={config.approverNote ?? ''}
          onChange={(e) => onChange({ ...config, approverNote: e.target.value })}
          placeholder="Anything the approver should specifically look at before signing off."
        />
      </Field>
    </div>
  );
}
