import { cn } from "@/lib/utils";

export function Table({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  );
}

export function THead({ children }: { children: React.ReactNode }) {
  return (
    <thead className="border-b border-border text-left text-[11px] font-medium uppercase tracking-wide text-muted">
      {children}
    </thead>
  );
}

export function Th({
  children,
  className,
  align = "left",
}: {
  children?: React.ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
}) {
  return (
    <th
      scope="col"
      className={cn(
        "whitespace-nowrap px-3 py-2 font-medium",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Tr({ children, className }: { children: React.ReactNode; className?: string }) {
  return <tr className={cn("border-b border-border last:border-0 hover:bg-panel-2/60", className)}>{children}</tr>;
}

export function Td({
  children,
  className,
  align = "left",
  title,
}: {
  children?: React.ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
  title?: string;
}) {
  return (
    <td
      title={title}
      className={cn(
        "px-3 py-2 align-middle text-text",
        align === "right" && "tabular text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </td>
  );
}
