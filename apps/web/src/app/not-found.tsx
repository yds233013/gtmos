import Link from "next/link";

import { EmptyState } from "@/components/ui/states";

export default function NotFound() {
  return (
    <EmptyState
      title="Not found"
      description="That record doesn't exist or was merged into another."
      action={
        <Link href="/" className="text-sm text-accent-text underline">
          Back to overview
        </Link>
      }
    />
  );
}
