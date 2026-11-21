import { Star } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Business } from "@/lib/api";
import { fmtDecimal, fmtDistance, fmtInt, fmtYears, splitCategories } from "@/lib/format";

/** Ficha de un negocio: la que se ve al pasar el cursor sobre su punto en el mapa. */
export function BusinessInfo({ business }: { business: Business }) {
  const { shown, extra } = splitCategories(business.categories);
  const place = [business.address, business.city, business.state].filter(Boolean).join(", ");
  const isOpen = business.is_open === 1;

  return (
    <div className="space-y-1.5">
      <div className="flex items-start justify-between gap-3">
        <strong className="text-sm font-semibold leading-snug">{business.name}</strong>
        <Badge tone={isOpen ? "open" : "closed"} className="shrink-0">
          <span aria-hidden="true" className={`inline-block size-2 rounded-full ${isOpen ? "bg-open" : "border-2 border-closed"}`} />
          {isOpen ? "Abierto" : "Cerrado"}
        </Badge>
      </div>

      <p className="flex items-center gap-1.5 tnum">
        <Star className="size-3.5 fill-current text-[var(--okabe-orange)]" aria-hidden="true" />
        <span className="font-medium">{fmtDecimal(business.stars, 1)}</span>
        <span className="text-muted-foreground">· {fmtInt(business.review_count)} reseñas</span>
      </p>

      {shown.length > 0 ? (
        <p className="text-muted-foreground">
          {shown.join(" · ")}
          {extra > 0 ? ` · +${extra}` : ""}
        </p>
      ) : null}
      {place ? <p className="text-muted-foreground">{place}</p> : null}

      <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground tnum">
        {business.distance_m != null ? <span>A {fmtDistance(business.distance_m)} del centro</span> : null}
        <span>Vida observada: {fmtYears(business.days_business)}</span>
      </p>
    </div>
  );
}
