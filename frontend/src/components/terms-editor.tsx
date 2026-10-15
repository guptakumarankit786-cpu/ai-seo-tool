"use client";

import { useId, useState } from "react";
import { Badge, Button } from "@/components/ui";

/**
 * Inline chips + "Edit" → comma-separated input. Used for brand terms and competitor terms.
 * `onSave(null)` means "reset to the suggestion" (only offered when `suggested` is given).
 */
export function TermsEditor({
  label,
  hint,
  placeholder,
  terms,
  isDefault = false,
  suggested,
  onSave,
}: {
  label: string;
  hint: string;
  placeholder: string;
  terms: string[];
  isDefault?: boolean;
  suggested?: string[];
  onSave: (terms: string[] | null) => Promise<void>;
}) {
  const inputId = useId();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (value: string[] | null) => {
    setSaving(true);
    try {
      await onSave(value);
      setEditing(false);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    setSaving(false);
  };

  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
        <span className="text-xs text-muted">{label}:</span>
        {terms.length ? terms.map((t) => <Badge key={t}>{t}</Badge>) : <span className="text-xs">none</span>}
        {isDefault && <span className="text-xs text-muted">(suggested)</span>}
        <Button
          variant="secondary"
          className="ml-1"
          onClick={() => {
            setDraft(terms.join(", "));
            setEditing(true);
          }}
        >
          {terms.length ? "Edit" : "Add"}
        </Button>
      </div>
    );
  }

  return (
    <div className="w-full space-y-2 sm:max-w-md">
      <label className="block text-xs text-muted" htmlFor={inputId}>
        {hint}
      </label>
      <input
        id={inputId}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm"
        placeholder={placeholder}
        autoFocus
      />
      {error && <p className="text-xs text-negative">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={saving}
          onClick={() =>
            save(
              draft
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean),
            )
          }
        >
          Save
        </Button>
        <Button variant="secondary" disabled={saving} onClick={() => setEditing(false)}>
          Cancel
        </Button>
        {suggested && !isDefault && (
          <Button variant="secondary" disabled={saving} onClick={() => save(null)}>
            Reset to suggestion ({suggested.join(", ") || "none"})
          </Button>
        )}
      </div>
    </div>
  );
}
