import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { classLabel, fmtInt, fmtPercent } from "@/lib/format";
import { CLASS_BAR } from "./shared";

interface Props {
  distribution: Record<string, number>;
  classes: string[];
  total: number;
}

export function ClassDistribution({ distribution, classes, total }: Props) {
  const rows = classes.map((name) => ({ name, count: distribution[name] ?? 0, share: total ? ((distribution[name] ?? 0) / total) * 100 : 0 }));
  const dominant = [...rows].sort((a, b) => b.count - a.count)[0];

  return (
    <Card aria-labelledby="distribution-title">
      <CardHeader
        id="distribution-title"
        title="Distribución de las clases"
        description="La etiqueta sale de las estrellas de cada reseña: 1-2 negativo, 3 neutral, 4-5 positivo."
      />
      <CardContent className="space-y-4">
        <div
          role="img"
          aria-label={`Distribución de ${fmtInt(total)} reseñas: ${rows.map((r) => `${classLabel(r.name)} ${fmtPercent(r.share)}`).join(", ")}`}
          className="flex h-4 overflow-hidden rounded-full bg-muted"
        >
          {rows.map((row) => (
            <div key={row.name} className={CLASS_BAR[row.name] ?? "bg-neutral"} style={{ width: `${row.share}%` }} />
          ))}
        </div>

        <table className="w-full text-sm">
          <caption className="sr-only">Reseñas por clase</caption>
          <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th scope="col" className="py-1.5 font-medium">Clase</th>
              <th scope="col" className="py-1.5 text-right font-medium">Reseñas</th>
              <th scope="col" className="py-1.5 text-right font-medium">Parte</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="border-t border-border">
                <th scope="row" className="py-2 text-left font-medium">
                  <span className="inline-flex items-center gap-2">
                    <span aria-hidden="true" className={`size-2.5 rounded-sm ${CLASS_BAR[row.name] ?? "bg-neutral"}`} />
                    {classLabel(row.name)}
                  </span>
                </th>
                <td className="py-2 text-right tnum">{fmtInt(row.count)}</td>
                <td className="py-2 text-right tnum">{fmtPercent(row.share)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {dominant ? (
          dominant.share >= 50 ? (
            <p className="text-sm text-muted-foreground">
              Está <strong className="text-foreground">desbalanceada</strong>: «{dominant.name}» es el {fmtPercent(dominant.share, 0)} de las reseñas. Por eso se entrena con pesos inversos a la frecuencia de cada clase y se compara con F1 macro, no solo con accuracy.
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">Ninguna clase supera la mitad de las reseñas.</p>
          )
        ) : null}
      </CardContent>
    </Card>
  );
}
