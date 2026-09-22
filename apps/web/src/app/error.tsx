"use client";

import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="space-y-3">
      <ErrorState title="This page failed to load" message={error.message} />
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
