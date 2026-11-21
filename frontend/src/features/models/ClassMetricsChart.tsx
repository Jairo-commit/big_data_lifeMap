import { useId, useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Segmented } from "@/components/ui/segmented";
import type { ModelsInfo } from "@/lib/api";
import { classLabel, fmtDecimal, modelLabel } from "@/lib/format";
import { METRIC_LABELS, type MetricKey } from "@/lib/metrics";
import { cn } from "@/lib/utils";
import { modelSwatch } from "./shared";

const W = 640;
const H = 300;
const M = { top: 24, right: 12, bottom: 40, left: 40 };
const TICKS = [0, 0.25, 0.5, 0.75, 1];

export function ClassMetricsChart({ info }: { info: ModelsInfo }) {
  const [metric, setMetric] = useState<MetricKey>("f1");
  const uid = useId();
  const patternId = `${uid}-hatch`;
  const names = Object.keys(info.models);
  const classes = info.classes;

  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const groupW = plotW / Math.max(classes.length, 1);
  const barW = Math.min(46, (groupW * 0.7) / Math.max(names.length, 1));
  const y = (v: number) => M.top + plotH * (1 - v);

  return (
    <Card aria-labelledby="class-metrics-title">
      <CardHeader
        id="class-metrics-title"
        title="Métricas por clase"
        description="Con clases desbalanceadas el promedio global esconde dónde falla cada modelo."
        action={
          <Segmented
            legend="Métrica"
            value={metric}
            onChange={setMetric}
            options={(Object.keys(METRIC_LABELS) as MetricKey[]).map((key) => ({ value: key, label: METRIC_LABELS[key] }))}
          />
        }
      />
      <CardContent className="space-y-4">
        <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm" aria-label="Leyenda">
          {names.map((name) => (
            <li key={name} className="flex items-center gap-2">
              <svg width="16" height="16" aria-hidden="true">
                <rect width="16" height="16" rx="3" style={{ fill: name === info.best_model ? "var(--model-best)" : "var(--model-other)" }} />
                {name !== info.best_model ? <rect width="16" height="16" rx="3" fill={`url(#${patternId})`} /> : null}
              </svg>
              {modelLabel(name)}
            </li>
          ))}
        </ul>

        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={`${uid}-t ${uid}-d`} className="h-auto w-full">
          <title id={`${uid}-t`}>{METRIC_LABELS[metric]} por clase y modelo</title>
          <desc id={`${uid}-d`}>
            {classes
              .map((c) => `${classLabel(c)}: ${names.map((n) => `${modelLabel(n)} ${fmtDecimal(info.models[n]?.per_class[c]?.[metric], 3)}`).join(", ")}`)
              .join(". ")}
          </desc>
          <defs>
            <pattern id={patternId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="2.5" height="6" fill="var(--card)" opacity="0.55" />
            </pattern>
          </defs>

          {TICKS.map((tick) => (
            <g key={tick}>
              <line x1={M.left} x2={W - M.right} y1={y(tick)} y2={y(tick)} style={{ stroke: "var(--chart-grid)" }} strokeWidth="1" />
              <text x={M.left - 8} y={y(tick) + 4} textAnchor="end" fontSize="11" style={{ fill: "var(--chart-axis)" }} className="tnum">
                {fmtDecimal(tick, 2)}
              </text>
            </g>
          ))}

          {classes.map((cls, ci) => {
            const gx = M.left + ci * groupW + groupW / 2;
            return (
              <g key={cls}>
                {names.map((name, ni) => {
                  const value = info.models[name]?.per_class[cls]?.[metric] ?? 0;
                  const x = gx - (names.length * barW) / 2 + ni * barW + 2;
                  const isBest = name === info.best_model;
                  return (
                    <g key={name}>
                      <rect x={x} y={y(value)} width={barW - 4} height={plotH * value} rx="3" style={{ fill: isBest ? "var(--model-best)" : "var(--model-other)" }} />
                      {!isBest ? <rect x={x} y={y(value)} width={barW - 4} height={plotH * value} rx="3" fill={`url(#${patternId})`} /> : null}
                      <text x={x + (barW - 4) / 2} y={y(value) - 6} textAnchor="middle" fontSize="12" fontWeight="600" style={{ fill: "var(--foreground)" }} className="tnum">
                        {fmtDecimal(value, 2)}
                      </text>
                    </g>
                  );
                })}
                <text x={gx} y={H - 14} textAnchor="middle" fontSize="13" fontWeight="500" style={{ fill: "var(--foreground)" }}>
                  {classLabel(cls)}
                </text>
              </g>
            );
          })}
        </svg>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <caption className="sr-only">Precision, recall y F1 por clase y modelo</caption>
            <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th scope="col" className="py-2 pr-3 font-medium">Clase</th>
                <th scope="col" className="py-2 pr-3 font-medium">Modelo</th>
                {(Object.keys(METRIC_LABELS) as MetricKey[]).map((key) => (
                  <th key={key} scope="col" className={cn("py-2 pr-3 text-right font-medium", key === metric && "text-foreground")}>
                    {METRIC_LABELS[key]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {classes.flatMap((cls) =>
                names.map((name, ni) => (
                  <tr key={`${cls}-${name}`} className={cn("border-t border-border", ni > 0 && "border-t-0")}>
                    {ni === 0 ? (
                      <th scope="rowgroup" rowSpan={names.length} className="py-2 pr-3 text-left align-top font-medium">
                        {classLabel(cls)}
                      </th>
                    ) : null}
                    <td className="py-1.5 pr-3">
                      <span className="inline-flex items-center gap-2">
                        <span aria-hidden="true" className={cn("size-2.5 rounded-sm", modelSwatch(name === info.best_model))} />
                        {modelLabel(name)}
                      </span>
                    </td>
                    {(Object.keys(METRIC_LABELS) as MetricKey[]).map((key) => (
                      <td key={key} className={cn("py-1.5 pr-3 text-right tnum", key === metric ? "font-semibold" : "text-muted-foreground")}>
                        {fmtDecimal(info.models[name]?.per_class[cls]?.[key], 4)}
                      </td>
                    ))}
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
