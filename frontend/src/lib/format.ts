const LOCALE = "es-CO";

const int = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 1 });

export const fmtInt = (n: number | null | undefined) => (n == null ? "—" : int.format(n));
export const fmtCompact = (n: number | null | undefined) => (n == null ? "—" : compact.format(n));

export function fmtDecimal(n: number | null | undefined, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

/** Recibe un porcentaje ya en escala 0-100 (así lo devuelve la API de zonas). */
export const fmtPercent = (n: number | null | undefined, digits = 1) =>
  n == null || Number.isNaN(n) ? "—" : `${fmtDecimal(n, digits)} %`;

/** Recibe una proporción 0-1 (así salen las métricas de los modelos). */
export const fmtRatioAsPercent = (n: number | null | undefined, digits = 1) =>
  n == null || Number.isNaN(n) ? "—" : fmtPercent(n * 100, digits);

export function fmtDistance(meters: number | null | undefined) {
  if (meters == null) return "—";
  return meters < 1000 ? `${int.format(meters)} m` : `${fmtDecimal(meters / 1000, 1)} km`;
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(LOCALE, { dateStyle: "long", timeStyle: "short" }).format(date);
}

/** Años aproximados a partir de días de vida (el dataset no trae fechas de apertura ni de cierre). */
export function fmtYears(days: number | null | undefined) {
  if (days == null) return "—";
  const years = days / 365;
  return years < 1 ? `${int.format(days)} días` : `${fmtDecimal(years, 1)} años`;
}

/** "Pizza, Italian, Restaurants, Food" → ["Pizza", "Italian", "Restaurants"] (+1 más) */
export function splitCategories(categories: string | null | undefined, max = 3) {
  const all = (categories ?? "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
  return { shown: all.slice(0, max), extra: Math.max(0, all.length - max) };
}

/** "naive_bayes" → "Naive Bayes", "logistic_regression" → "Regresión logística". */
export function modelLabel(name: string) {
  const known: Record<string, string> = {
    naive_bayes: "Naive Bayes",
    logistic_regression: "Regresión logística",
  };
  return known[name] ?? name.replaceAll("_", " ");
}

export const classLabel = (name: string) => name.charAt(0).toUpperCase() + name.slice(1);
