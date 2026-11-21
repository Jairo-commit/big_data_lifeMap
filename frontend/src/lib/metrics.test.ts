import { describe, expect, it } from "vitest";
import type { ModelMetrics } from "./api";
import { accuracyFromMatrix, bestByF1Macro, confusionInsights, heatBackground, rowPercentages } from "./metrics";

const CLASSES = ["negativo", "neutral", "positivo"];

describe("rowPercentages", () => {
  it("expresa cada celda como porcentaje de su fila", () => {
    const row = { negativo: 50, neutral: 25, positivo: 25 };
    expect(rowPercentages(row, CLASSES)).toEqual({ negativo: 50, neutral: 25, positivo: 25 });
  });

  it("una fila vacía da 0 % en todas las celdas (sin dividir entre cero)", () => {
    expect(rowPercentages({}, CLASSES)).toEqual({ negativo: 0, neutral: 0, positivo: 0 });
  });
});

describe("accuracyFromMatrix", () => {
  it("suma la diagonal sobre el total", () => {
    const matrix = {
      negativo: { negativo: 8, neutral: 1, positivo: 1 },
      neutral: { negativo: 0, neutral: 5, positivo: 5 },
      positivo: { negativo: 0, neutral: 0, positivo: 10 },
    };
    expect(accuracyFromMatrix(matrix, CLASSES)).toBeCloseTo(23 / 30);
  });

  it("sin datos no hay accuracy", () => {
    expect(accuracyFromMatrix({}, CLASSES)).toBeNull();
  });
});

describe("bestByF1Macro", () => {
  const metrics = (f1_macro: number): ModelMetrics => ({
    accuracy: 0,
    f1_macro,
    f1_weighted: 0,
    per_class: {},
    confusion_matrix: {},
  });

  it("elige el de mayor F1 macro", () => {
    expect(bestByF1Macro({ naive_bayes: metrics(0.63), logistic_regression: metrics(0.73) })).toBe("logistic_regression");
  });

  it("sin modelos devuelve null", () => {
    expect(bestByF1Macro({})).toBeNull();
  });
});

describe("heatBackground", () => {
  it("acota el valor entre 0 y 100 y nunca pasa del 48 % de intensidad", () => {
    expect(heatBackground(250)).toContain("48%");
    expect(heatBackground(-5)).toContain(" 0%");
  });

  it("se mezcla con el color de la tarjeta, no con transparente", () => {
    expect(heatBackground(50)).toContain("var(--card)");
  });
});

describe("confusionInsights", () => {
  const model: ModelMetrics = {
    accuracy: 0.8,
    f1_macro: 0.7,
    f1_weighted: 0.8,
    per_class: {
      negativo: { precision: 0.8, recall: 0.8, f1: 0.8 },
      neutral: { precision: 0.3, recall: 0.6, f1: 0.4 },
      positivo: { precision: 0.9, recall: 0.9, f1: 0.9 },
    },
    confusion_matrix: {
      negativo: { negativo: 80, neutral: 15, positivo: 5 },
      neutral: { negativo: 10, neutral: 60, positivo: 30 },
      positivo: { negativo: 5, neutral: 100, positivo: 895 },
    },
  };

  it("encuentra la clase más difícil y el error más frecuente", () => {
    const insights = confusionInsights(model, CLASSES);
    expect(insights.hardest).toEqual({ name: "neutral", f1: 0.4 });
    expect(insights.topConfusion).toEqual({ real: "positivo", predicted: "neutral", count: 100 });
  });

  it("sin datos no inventa nada", () => {
    const empty = { ...model, per_class: {}, confusion_matrix: {} };
    expect(confusionInsights(empty, CLASSES)).toEqual({ hardest: null, topConfusion: null });
  });
});
