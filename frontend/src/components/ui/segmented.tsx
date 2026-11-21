import { useId, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  hint?: string;
  icon?: ReactNode;
}

interface SegmentedProps<T extends string> {
  legend: string;
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  className?: string;
  /** "stack" apila las opciones (panel lateral); "inline" las deja en una fila. */
  layout?: "stack" | "inline";
}

/** Grupo de radios nativos con aspecto de control segmentado: teclado (flechas) y lectores de pantalla gratis. */
export function Segmented<T extends string>({
  legend,
  value,
  onChange,
  options,
  className,
  layout = "inline",
}: SegmentedProps<T>) {
  const name = useId();
  return (
    <fieldset className={cn("min-w-0", className)}>
      <legend className="mb-1.5 text-sm font-medium">{legend}</legend>
      <div
        className={cn(
          "gap-1 rounded-[var(--input-radius)] border border-border bg-muted p-1",
          layout === "stack" ? "grid" : "flex flex-wrap",
        )}
      >
        {options.map((option) => (
          <label
            key={option.value}
            className={cn(
              "relative flex min-h-9 flex-1 cursor-pointer items-center gap-2 rounded-[calc(var(--input-radius)-2px)] px-3 py-1.5 text-sm transition-colors duration-150 pointer-coarse:min-h-11",
              "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ring",
              value === option.value
                ? "bg-card font-medium text-foreground shadow-sm ring-1 ring-border"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {option.icon}
            <span className="min-w-0">
              <span className="block">{option.label}</span>
              {option.hint ? <span className="block text-xs font-normal text-muted-foreground">{option.hint}</span> : null}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
