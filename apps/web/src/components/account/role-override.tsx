"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { clientApi } from "@/lib/client-api";

export function RoleOverride({
  accountId,
  role,
  options,
  current,
  manual,
}: {
  accountId: string;
  role: string;
  options: { id: string; label: string }[];
  current: string | null;
  manual: boolean;
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);

  async function change(contactId: string) {
    setError(null);
    try {
      if (contactId === "__auto__") {
        await clientApi(`/accounts/${accountId}/committee/${role}`, { method: "DELETE" });
      } else {
        await clientApi(`/accounts/${accountId}/committee/${role}`, { method: "PUT", body: { contact_id: contactId } });
      }
      start(() => router.refresh());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  return (
    <div>
      <label className="sr-only" htmlFor={`override-${role}`}>
        Override {role}
      </label>
      <select
        id={`override-${role}`}
        disabled={pending}
        value={manual && current ? current : "__placeholder__"}
        onChange={(e) => change(e.target.value)}
        className="h-7 w-full rounded border border-border bg-panel px-1.5 text-[11px] text-muted"
      >
        <option value="__placeholder__" disabled>
          {manual ? "Manual override" : "Override…"}
        </option>
        {manual && <option value="__auto__">Clear override (use inference)</option>}
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
      {error && <p className="mt-1 text-[11px] text-danger">{error}</p>}
    </div>
  );
}
