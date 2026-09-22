"use client";

import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
}

/**
 * Labelled <select> inside a GET form. Changing it submits the form, so filters stay in the URL and
 * pages remain server-rendered. The surrounding form keeps an explicit submit button for no-JS use.
 */
export function AutoSubmitSelect({
  name,
  label,
  options,
  value,
  className,
}: {
  name: string;
  label: string;
  options: SelectOption[];
  value: string | undefined;
  className?: string;
}) {
  const id = `filter-${name}`;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={id} className="text-[11px] font-medium text-muted">
        {label}
      </label>
      <select
        key={value ?? ""}
        id={id}
        name={name}
        defaultValue={value ?? ""}
        onChange={(e) => e.currentTarget.form?.requestSubmit()}
        className="h-8 min-w-0 rounded-md border border-border bg-panel px-2 text-xs text-text hover:border-border-strong"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
