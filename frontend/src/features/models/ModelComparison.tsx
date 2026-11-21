import { Trophy } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { ModelsInfo } from "@/lib/api";
import { fmtDecimal, fmtRatioAsPercent, modelLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { modelSwatch } from "./shared";

const METRICS = [
  { key: "accuracy", label: "Accuracy", hint: "Aciertos sobre el total" },
  { key: "f1_macro", label: "F1 macro", hint: "Promedio de F1 de las clases, todas pesan igual" },
  { key: "f1_weighted", label: "F1 ponderado", hint: "Promedio de F1 ponderado por el tamaño de cada clase" },
] as const;

export function ModelComparison({ info }: { info: ModelsInfo }) {
  const names = Object.keys(info.models);

  return (
    <Card aria-labelledby="comparison-title">
      <CardHeader
        id="comparison-title"
        title="Comparación de modelos"
        description="Evaluados con negocios que no vieron al entrenar. El mejor se elige por F1 macro."
      />
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] text-sm">
            <caption className="sr-only">Métricas globales por modelo</caption>
            <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th scope="col" className="py-2 pr-3 font-medium">Métrica</th>
                {names.map((name) => (
                  <th key={name} scope="col" className="py-2 pr-3 font-medium">
                    <span className="inline-flex flex-wrap items-center gap-2">
                      <span aria-hidden="true" className={cn("size-2.5 rounded-sm", modelSwatch(name === info.best_model))} />
                      <span className="normal-case tracking-normal text-foreground">{modelLabel(name)}</span>
                      {name === info.best_model ? (
                        <Badge tone="primary" className="normal-case tracking-normal">
                          <Trophy className="size-3" aria-hidden="true" /> Mejor
                        </Badge>
                      ) : null}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRICS.map((metric) => {
                const values = names.map((n) => info.models[n]?.[metric.key] ?? 0);
                const top = Math.max(...values);
                return (
                  <tr key={metric.key} className="border-t border-border align-top">
                    <th scope="row" className="py-3 pr-3 text-left font-medium">
                      {metric.label}
                      <span className="block text-xs font-normal text-muted-foreground">{metric.hint}</span>
                    </th>
                    {names.map((name, index) => {
                      const value = values[index] ?? 0;
                      return (
                        <td key={name} className="py-3 pr-3">
                          <div className={cn("tnum", value === top ? "font-semibold" : "text-muted-foreground")}>
                            {fmtDecimal(value, 4)} <span className="text-xs font-normal text-muted-foreground">({fmtRatioAsPercent(value)})</span>
                          </div>
                          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                            <div className={cn("h-full rounded-full", modelSwatch(name === info.best_model))} style={{ width: `${value * 100}%` }} />
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
