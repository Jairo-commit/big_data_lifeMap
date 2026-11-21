import { describe, expect, it } from "vitest";
import { fmtDistance, fmtPercent, fmtRatioAsPercent, fmtYears, modelLabel, splitCategories } from "./format";

describe("fmtDistance", () => {
  it("usa metros por debajo de 1 km y kilómetros por encima", () => {
    expect(fmtDistance(2.6)).toMatch(/^3 m$/);
    expect(fmtDistance(1500)).toMatch(/^1,5 km$/);
  });

  it("sin dato muestra un guion", () => {
    expect(fmtDistance(undefined)).toBe("—");
  });
});

describe("porcentajes", () => {
  it("fmtPercent recibe una escala 0-100", () => {
    expect(fmtPercent(17.706, 1)).toBe("17,7 %");
  });

  it("fmtRatioAsPercent recibe una proporción 0-1", () => {
    expect(fmtRatioAsPercent(0.8262, 1)).toBe("82,6 %");
  });

  it("los valores nulos o NaN dan un guion", () => {
    expect(fmtPercent(null)).toBe("—");
    expect(fmtRatioAsPercent(Number.NaN)).toBe("—");
  });
});

describe("fmtYears", () => {
  it("menos de un año se muestra en días", () => {
    expect(fmtYears(200)).toMatch(/^200 días$/);
  });

  it("un año o más se muestra en años con un decimal", () => {
    expect(fmtYears(730)).toBe("2,0 años");
  });
});

describe("splitCategories", () => {
  it("devuelve las primeras y cuántas quedaron fuera", () => {
    expect(splitCategories("Pizza, Italian, Restaurants, Food", 3)).toEqual({ shown: ["Pizza", "Italian", "Restaurants"], extra: 1 });
  });

  it("sin categorías no devuelve nada", () => {
    expect(splitCategories(null)).toEqual({ shown: [], extra: 0 });
  });
});

describe("modelLabel", () => {
  it("traduce los modelos conocidos y deja legible el resto", () => {
    expect(modelLabel("logistic_regression")).toBe("Regresión logística");
    expect(modelLabel("random_forest")).toBe("random forest");
  });
});
