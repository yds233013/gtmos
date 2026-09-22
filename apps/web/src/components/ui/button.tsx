import { Slot } from "@radix-ui/react-slot";

import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-white hover:opacity-90 border-transparent",
  secondary: "bg-panel text-text border-border hover:bg-panel-2",
  ghost: "bg-transparent text-muted border-transparent hover:bg-panel-2 hover:text-text",
  danger: "bg-panel text-danger border-danger/40 hover:bg-danger-soft",
};

export function Button({
  variant = "secondary",
  size = "md",
  asChild,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md";
  asChild?: boolean;
}) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      className={cn(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md border font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-sm",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}
