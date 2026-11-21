import type { Business } from "@/lib/api";

export type QueryMode = "near" | "within" | "zone";

export interface QueryResult {
  mode: QueryMode;
  /** Total que cumple la consulta, si la API lo informa (solo $geoWithin). */
  total: number | null;
  returned: number;
  elapsedMs: number;
  businesses: Business[];
}

/** El resumen de zona suma las reseñas de cada negocio: con 2 km ya tarda ~30 s, y crece con el radio. */
export const ZONE_MAX_RADIUS = 2000;

export const MODE_META: Record<QueryMode, { label: string; operator: string; hint: string; maxLimit: number; defaultLimit: number }> = {
  near: {
    label: "Cerca de un punto",
    operator: "$near",
    hint: "Negocios en un radio, del más cercano al más lejano",
    maxLimit: 200,
    defaultLimit: 100,
  },
  within: {
    label: "Dentro de un polígono",
    operator: "$geoWithin",
    hint: "Negocios dentro de un área que dibujas",
    maxLimit: 1000,
    defaultLimit: 200,
  },
  zone: {
    label: "Resumen de zona",
    operator: "$geoNear",
    hint: "Sentimiento y tasa de cierre de un radio",
    maxLimit: 200,
    defaultLimit: 100,
  },
};
