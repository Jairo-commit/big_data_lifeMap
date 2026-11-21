import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import type { Business } from "@/lib/api";
import { fmtDecimal, fmtDistance, fmtInt, fmtYears, splitCategories } from "@/lib/format";
import { cn } from "@/lib/utils";

type SortKey = "name" | "stars" | "review_count" | "days_business" | "distance_m";
type Direction = "asc" | "desc";

interface ResultsTableProps {
  businesses: Business[];
  highlightedId: string | null;
  onHover: (id: string | null) => void;
  showDistance: boolean;
}

function sortValue(business: Business, key: SortKey): string | number {
  const value = business[key];
  return value == null ? (key === "name" ? "" : -Infinity) : value;
}

export function ResultsTable({ businesses, highlightedId, onHover, showDistance }: ResultsTableProps) {
  const [sort, setSort] = useState<{ key: SortKey; direction: Direction } | null>(null);

  const rows = useMemo(() => {
    if (!sort) return businesses;
    const factor = sort.direction === "asc" ? 1 : -1;
    return [...businesses].sort((a, b) => {
      const x = sortValue(a, sort.key);
      const y = sortValue(b, sort.key);
      if (typeof x === "string" && typeof y === "string") return x.localeCompare(y, "es") * factor;
      return ((x as number) - (y as number)) * factor;
    });
  }, [businesses, sort]);

  function toggle(key: SortKey) {
    setSort((current) => {
      if (!current || current.key !== key) return { key, direction: key === "name" || key === "distance_m" ? "asc" : "desc" };
      return current.direction === "asc" ? { key, direction: "desc" } : null;
    });
  }

  const columns: { key: SortKey | null; label: string; className?: string }[] = [
    { key: "name", label: "Negocio" },
    { key: null, label: "Categorías" },
    { key: "stars", label: "Estrellas", className: "text-right" },
    { key: "review_count", label: "Reseñas", className: "text-right" },
    { key: null, label: "Estado" },
    { key: "days_business", label: "Vida observada", className: "text-right" },
    ...(showDistance ? [{ key: "distance_m" as const, label: "Distancia", className: "text-right" }] : []),
  ];

  return (
    <div className="max-h-[26rem] overflow-auto rounded-md border border-border">
      <table className="w-full min-w-[44rem] border-collapse text-sm">
        <caption className="sr-only">Negocios que cumplen la consulta. Pasa el cursor o el foco por una fila para resaltar su punto en el mapa.</caption>
        <thead className="sticky top-0 z-10 bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            {columns.map((column) => {
              const active = sort && column.key === sort.key ? sort : null;
              return (
                <th
                  key={column.label}
                  scope="col"
                  aria-sort={active ? (active.direction === "asc" ? "ascending" : "descending") : column.key ? "none" : undefined}
                  className={cn("px-3 py-2 font-medium", column.className)}
                >
                  {column.key ? (
                    <button
                      type="button"
                      onClick={() => toggle(column.key as SortKey)}
                      className={cn("inline-flex items-center gap-1 uppercase tracking-wide hover:text-foreground", column.className?.includes("right") && "w-full justify-end")}
                    >
                      {column.label}
                      {active ? (
                        active.direction === "asc" ? <ArrowUp className="size-3.5" aria-hidden="true" /> : <ArrowDown className="size-3.5" aria-hidden="true" />
                      ) : (
                        <ArrowUpDown className="size-3.5 opacity-50" aria-hidden="true" />
                      )}
                    </button>
                  ) : (
                    column.label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((business) => {
            const { shown, extra } = splitCategories(business.categories, 2);
            const isOpen = business.is_open === 1;
            return (
              <tr
                key={business.business_id}
                tabIndex={0}
                onMouseEnter={() => onHover(business.business_id)}
                onMouseLeave={() => onHover(null)}
                onFocus={() => onHover(business.business_id)}
                onBlur={() => onHover(null)}
                className={cn("border-t border-border align-top transition-colors duration-100", highlightedId === business.business_id ? "bg-accent" : "hover:bg-muted/60")}
              >
                <th scope="row" className="px-3 py-2 text-left font-medium">
                  <span className="block">{business.name}</span>
                  <span className="block text-xs font-normal text-muted-foreground">{[business.city, business.state].filter(Boolean).join(", ")}</span>
                </th>
                <td className="px-3 py-2 text-muted-foreground">
                  {shown.join(" · ")}
                  {extra > 0 ? ` · +${extra}` : ""}
                </td>
                <td className="px-3 py-2 text-right tnum">{fmtDecimal(business.stars, 1)}</td>
                <td className="px-3 py-2 text-right tnum">{fmtInt(business.review_count)}</td>
                <td className="px-3 py-2">
                  <Badge tone={isOpen ? "open" : "closed"}>
                    <span aria-hidden="true" className={`inline-block size-2 rounded-full ${isOpen ? "bg-open" : "border-2 border-closed"}`} />
                    {isOpen ? "Abierto" : "Cerrado"}
                  </Badge>
                </td>
                <td className="px-3 py-2 text-right tnum">{fmtYears(business.days_business)}</td>
                {showDistance ? <td className="px-3 py-2 text-right tnum">{fmtDistance(business.distance_m)}</td> : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
