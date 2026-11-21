import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "border-border bg-muted text-foreground",
        primary: "border-primary/30 bg-accent text-accent-foreground",
        open: "border-open/40 bg-open/10 text-foreground",
        closed: "border-closed/40 bg-closed/10 text-foreground",
        danger: "border-destructive/40 bg-destructive-surface text-destructive",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
