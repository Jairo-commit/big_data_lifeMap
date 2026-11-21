/** Cliente de la API de LifeMap. En desarrollo y en producción se llama a /api (proxy sin CORS). */

export type LonLat = [number, number];

export interface Business {
  business_id: string;
  name: string;
  address?: string;
  city?: string;
  state?: string;
  stars?: number;
  review_count?: number;
  is_open?: 0 | 1;
  categories?: string | null;
  location: { type: "Point"; coordinates: LonLat };
  /** Días entre la primera y la última reseña. */
  days_business?: number;
  /** 1 = cierre observado, 0 = censurado (sigue abierto). */
  event?: 0 | 1;
  /** Distancia al centro de la consulta, solo en $near. */
  distance_m?: number;
}

export interface PolygonGeometry {
  type: "Polygon";
  coordinates: LonLat[][];
}

export interface NearResponse {
  center: { type: "Point"; coordinates: LonLat };
  radius_m: number;
  category: string | null;
  returned: number;
  businesses: Business[];
}

export interface WithinResponse {
  geometry: PolygonGeometry;
  category: string | null;
  total: number;
  returned: number;
  businesses: Business[];
}

export interface ZoneSummary {
  center: { type: "Point"; coordinates: LonLat };
  radius_m: number;
  category: string | null;
  n_businesses: number;
  closure: {
    closures: number;
    business_days: number;
    closure_rate: number | null;
    min_business_days: number;
    meets_min_days: boolean;
  };
  sentiment: {
    n_reviews: number;
    mean_stars: number | null;
    sentiment_score: number | null;
    pct_negative: number | null;
    pct_neutral: number | null;
    pct_positive: number | null;
  };
}

export type SentimentClass = "negativo" | "neutral" | "positivo";

export interface ClassMetrics {
  precision: number;
  recall: number;
  f1: number;
}

export interface ModelMetrics {
  accuracy: number;
  f1_macro: number;
  f1_weighted: number;
  per_class: Record<string, ClassMetrics>;
  /** Filas = clase real, columnas = clase predicha. */
  confusion_matrix: Record<string, Record<string, number>>;
}

export interface ModelsInfo {
  task: string;
  trained_at: string | null;
  reviews: number;
  class_distribution: Record<string, number>;
  classes: string[];
  cutoff: string | null;
  sample_fraction: number | null;
  best_model: string;
  models: Record<string, ModelMetrics>;
}

export interface Prediction {
  text: string;
  sentiment: SentimentClass;
  probabilities: Record<string, number>;
}

export interface Health {
  status: "ok" | "degraded";
  commit_hash: string;
  services: Record<string, string>;
}

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("No se pudo conectar con la API. ¿Está en marcha?", 0);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const data = (body ?? {}) as { error?: string; detail?: string };
    const message = data.detail ?? data.error ?? `La API respondió ${response.status}`;
    throw new ApiError(message, response.status, data.error);
  }
  return body as T;
}

function query(params: Record<string, string | number | undefined | null>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export interface CircleQuery {
  lat: number;
  lon: number;
  radius: number;
  category?: string;
  limit?: number;
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/health", { signal }),

  models: (signal?: AbortSignal) => request<ModelsInfo>("/models", { signal }),

  predict: (text: string, signal?: AbortSignal) =>
    request<Prediction>("/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal,
    }),

  /** $near: negocios alrededor de un punto, del más cercano al más lejano. */
  near: (q: CircleQuery, signal?: AbortSignal) =>
    request<NearResponse>(`/businesses/near${query({ ...q })}`, { signal }),

  /** $geoWithin: negocios dentro de un polígono GeoJSON. */
  within: (polygon: PolygonGeometry, q: { category?: string; limit?: number }, signal?: AbortSignal) =>
    request<WithinResponse>(`/businesses/within${query({ ...q })}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(polygon),
      signal,
    }),

  /** $geoNear: sentimiento medio y tasa de cierre alrededor de un punto. */
  zone: (q: Omit<CircleQuery, "limit"> & { min_days?: number }, signal?: AbortSignal) =>
    request<ZoneSummary>(`/zones/summary${query({ ...q })}`, { signal }),
};
