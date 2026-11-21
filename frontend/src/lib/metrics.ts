import type { ModelMetrics } from "./api";

/** Cada fila de la matriz de confusión como porcentaje de la clase real (recall por celda). */
export function rowPercentages(row: Record<string, number>, classes: string[]): Record<string, number> {
  const total = classes.reduce((sum, c) => sum + (row[c] ?? 0), 0);
  return Object.fromEntries(classes.map((c) => [c, total === 0 ? 0 : ((row[c] ?? 0) / total) * 100]));
}

/** Verdaderos positivos y total de la matriz: el accuracy se puede recalcular y contrastar con el guardado. */
export function accuracyFromMatrix(matrix: Record<string, Record<string, number>>, classes: string[]) {
  let correct = 0;
  let total = 0;
  for (const real of classes) {
    for (const predicted of classes) {
      const count = matrix[real]?.[predicted] ?? 0;
      total += count;
      if (real === predicted) correct += count;
    }
  }
  return total === 0 ? null : correct / total;
}

export type MetricKey = "precision" | "recall" | "f1";

export const METRIC_LABELS: Record<MetricKey, string> = {
  precision: "Precision",
  recall: "Recall",
  f1: "F1",
};

/** El modelo con mayor F1 macro (el criterio con el que el job elige `sentiment_best`). */
export function bestByF1Macro(models: Record<string, ModelMetrics>): string | null {
  let best: string | null = null;
  for (const [name, metrics] of Object.entries(models)) {
    if (best === null || metrics.f1_macro > (models[best]?.f1_macro ?? -Infinity)) best = name;
  }
  return best;
}

/**
 * Fondo de una celda de la matriz de confusión: el color de marca mezclado con el de la tarjeta.
 * La intensidad se limita a ~48 % para que el texto del tema (claro u oscuro) mantenga contraste AA.
 */
export function heatBackground(percent: number) {
  const strength = Math.round(Math.min(100, Math.max(0, percent)) * 0.48);
  return `color-mix(in srgb, var(--heat-base) ${strength}%, var(--card))`;
}

export interface ConfusionInsights {
  /** La clase con menor F1. */
  hardest: { name: string; f1: number } | null;
  /** El error más frecuente: la clase real que más se predice como otra. */
  topConfusion: { real: string; predicted: string; count: number } | null;
}

export function confusionInsights(model: ModelMetrics, classes: string[]): ConfusionInsights {
  let hardest: ConfusionInsights["hardest"] = null;
  for (const name of classes) {
    const f1 = model.per_class[name]?.f1;
    if (f1 !== undefined && (hardest === null || f1 < hardest.f1)) hardest = { name, f1 };
  }

  let topConfusion: ConfusionInsights["topConfusion"] = null;
  for (const real of classes) {
    for (const predicted of classes) {
      if (real === predicted) continue;
      const count = model.confusion_matrix[real]?.[predicted] ?? 0;
      if (count > 0 && (topConfusion === null || count > topConfusion.count)) topConfusion = { real, predicted, count };
    }
  }
  return { hardest, topConfusion };
}
