import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Segmented } from "@/components/ui/segmented";
import type { ModelsInfo } from "@/lib/api";
import { classLabel, fmtDecimal, fmtInt, fmtPercent, modelLabel } from "@/lib/format";
import { confusionInsights, heatBackground, rowPercentages } from "@/lib/metrics";
import { cn } from "@/lib/utils";
import { modelSwatch } from "./shared";

type View = "percent" | "count";

function Matrix({ name, info, view }: { name: string; info: ModelsInfo; view: View }) {
  const classes = info.classes;
  const matrix = info.models[name]?.confusion_matrix ?? {};
  const isBest = name === info.best_model;

  return (
    <figure className="min-w-0">
      <figcaption className="mb-2 flex items-center gap-2 text-sm font-medium">
        <span aria-hidden="true" className={cn("size-2.5 rounded-sm", modelSwatch(isBest))} />
        {modelLabel(name)}
      </figcaption>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[22rem] border-separate border-spacing-1 text-center text-sm">
          <caption className="sr-only">
            Matriz de confusión de {modelLabel(name)}: filas, clase real; columnas, clase predicha.
          </caption>
          <thead>
            <tr>
              <td />
              <th scope="colgroup" colSpan={classes.length} className="pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Predicho
              </th>
            </tr>
            <tr>
              <th scope="col" className="text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">Real</th>
              {classes.map((c) => (
                <th key={c} scope="col" className="px-1 pb-1 text-xs font-medium">{classLabel(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {classes.map((real) => {
              const row = matrix[real] ?? {};
              const percents = rowPercentages(row, classes);
              return (
                <tr key={real}>
                  <th scope="row" className="pr-2 text-left text-xs font-medium">{classLabel(real)}</th>
                  {classes.map((predicted) => {
                    const percent = percents[predicted] ?? 0;
                    const diagonal = real === predicted;
                    return (
                      <td
                        key={predicted}
                        style={{ background: heatBackground(percent) }}
                        className={cn("rounded-md px-2 py-2.5 tnum", diagonal && "ring-2 ring-inset ring-foreground/30")}
                      >
                        <span className={cn("block font-semibold", !diagonal && "font-medium")}>
                          {view === "percent" ? fmtPercent(percent, 1) : fmtInt(row[predicted] ?? 0)}
                        </span>
                        <span className="block text-xs">
                          {view === "percent" ? fmtInt(row[predicted] ?? 0) : fmtPercent(percent, 1)}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </figure>
  );
}

export function ConfusionMatrices({ info }: { info: ModelsInfo }) {
  const [view, setView] = useState<View>("percent");
  const names = Object.keys(info.models);
  const best = info.models[info.best_model];
  const insights = best ? confusionInsights(best, info.classes) : { hardest: null, topConfusion: null };

  return (
    <Card aria-labelledby="confusion-title">
      <CardHeader
        id="confusion-title"
        title="Matrices de confusión"
        description="Qué predijo el modelo (columnas) para cada clase real (filas). La diagonal, con borde, son los aciertos."
        action={
          <Segmented
            legend="Mostrar"
            value={view}
            onChange={setView}
            options={[
              { value: "percent", label: "% de la fila" },
              { value: "count", label: "Cantidad" },
            ]}
          />
        }
      />
      <CardContent className="space-y-4">
        <div className="grid gap-6 xl:grid-cols-2">
          {names.map((name) => (
            <Matrix key={name} name={name} info={info} view={view} />
          ))}
        </div>
        {insights.hardest ? (
          <p className="text-sm text-muted-foreground">
            Para {modelLabel(info.best_model)}, la clase más difícil es <strong className="text-foreground">«{insights.hardest.name}»</strong> (F1 {fmtDecimal(insights.hardest.f1, 2)}).
            {insights.topConfusion ? (
              <>
                {" "}El error más frecuente: <strong className="text-foreground">{fmtInt(insights.topConfusion.count)}</strong> reseñas «{insights.topConfusion.real}» clasificadas como «{insights.topConfusion.predicted}».
              </>
            ) : null}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
