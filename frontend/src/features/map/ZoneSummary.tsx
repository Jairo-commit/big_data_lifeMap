import { Info, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import type { ZoneSummary as ZoneSummaryData } from "@/lib/api";
import { fmtDecimal, fmtDistance, fmtInt, fmtPercent } from "@/lib/format";

interface ZoneSummaryProps {
  loading: boolean;
  data: ZoneSummaryData | null;
}

function SentimentBar({ negative, neutral, positive }: { negative: number; neutral: number; positive: number }) {
  const parts = [
    { key: "Negativo", value: negative, className: "bg-negative" },
    { key: "Neutral", value: neutral, className: "bg-neutral" },
    { key: "Positivo", value: positive, className: "bg-positive" },
  ];
  return (
    <div>
      <div
        role="img"
        aria-label={`Reseñas: ${fmtPercent(negative)} negativas, ${fmtPercent(neutral)} neutrales, ${fmtPercent(positive)} positivas`}
        className="flex h-3 overflow-hidden rounded-full bg-muted"
      >
        {parts.map((p) => (
          <div key={p.key} className={p.className} style={{ width: `${p.value}%` }} />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm tnum">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center gap-1.5">
            <span aria-hidden="true" className={`size-2.5 rounded-sm ${p.className}`} />
            {p.key} <strong className="font-semibold">{fmtPercent(p.value)}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ZoneSummary({ loading, data }: ZoneSummaryProps) {
  return (
    <Card aria-labelledby="zone-title" aria-busy={loading}>
      <CardHeader
        id="zone-title"
        as="h3"
        title="Resumen de la zona"
        description={data ? `${fmtInt(data.n_businesses)} negocios a menos de ${fmtDistance(data.radius_m)} del centro` : "Agregación $geoNear + $lookup + $group sobre negocios y reseñas"}
        action={data ? <Badge tone={data.closure.meets_min_days ? "primary" : "danger"}>{data.closure.meets_min_days ? "Tasa comparable" : "Pocos datos para comparar"}</Badge> : undefined}
      />
      <CardContent>
        {loading && !data ? (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Calculando el resumen: suma las reseñas de cada negocio y puede tardar varios segundos…
          </p>
        ) : null}

        {data ? (
          <div className="space-y-5">
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Negocios" value={fmtInt(data.n_businesses)} />
              <Stat
                label="Tasa de cierre"
                value={data.closure.closure_rate == null ? "—" : `${fmtDecimal(data.closure.closure_rate, 2)} %`}
                hint="anual, por 100 negocios-año"
              />
              <Stat label="Cierres observados" value={fmtInt(data.closure.closures)} hint={`${fmtInt(Math.round(data.closure.business_days / 365))} años-negocio`} />
              <Stat label="Estrellas medias" value={fmtDecimal(data.sentiment.mean_stars, 2)} hint={`${fmtInt(data.sentiment.n_reviews)} reseñas`} />
            </dl>

            {data.sentiment.pct_negative != null && data.sentiment.pct_neutral != null && data.sentiment.pct_positive != null ? (
              <div>
                <h4 className="mb-2 text-sm font-medium">Sentimiento de las reseñas</h4>
                <SentimentBar negative={data.sentiment.pct_negative} neutral={data.sentiment.pct_neutral} positive={data.sentiment.pct_positive} />
                <p className="mt-2 text-xs text-muted-foreground tnum">
                  Puntaje de sentimiento {fmtDecimal(data.sentiment.sentiment_score, 2)} (de −1, todo negativo, a 1, todo positivo).
                </p>
              </div>
            ) : null}

            <p className="flex gap-2 text-xs text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              <span>
                Tasa de cierre = cierres ÷ (días-negocio ÷ 365) × 100. Un negocio abierto cuenta sus días pero no un cierre (censura). Se compara solo con al menos {fmtInt(data.closure.min_business_days)} días-negocio.
              </span>
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
