import type { PolygonGeometry } from "@/lib/api";
import type { QueryMode } from "./types";

interface Params {
  lon: number;
  lat: number;
  radius: number;
  category: string;
  limit: number;
  minDays: number;
  polygon: PolygonGeometry | null;
}

const escapeRegex = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Mismo patrón que la API: la categoría debe ser un elemento completo de `categories`, sin importar mayúsculas. */
function categoryFilter(category: string) {
  return `{ $regex: ${JSON.stringify(`(^|,)\\s*${escapeRegex(category)}\\s*(,|$)`)}, $options: "i" }`;
}

const point = (lon: number, lat: number) => `{ type: "Point", coordinates: [${lon}, ${lat}] }`;

/** La consulta de MongoDB equivalente a lo que ejecuta la API para cada modo (en sintaxis de mongosh). */
export function mongoSnippet(mode: QueryMode, p: Params): string {
  const category = p.category.trim();
  if (mode === "near") {
    return `db.businesses.find({
  location: { $near: { $geometry: ${point(p.lon, p.lat)}, $maxDistance: ${p.radius} } },${
    category ? `\n  categories: ${categoryFilter(category)},` : ""
  }
}).limit(${p.limit})`;
  }

  if (mode === "within") {
    const ring = p.polygon?.coordinates[0] ?? [];
    const coordinates = ring.map(([lon, lat]) => `[${lon}, ${lat}]`).join(", ");
    return `db.businesses.find({
  location: { $geoWithin: { $geometry: { type: "Polygon", coordinates: [[${coordinates}]] } } },${
    category ? `\n  categories: ${categoryFilter(category)},` : ""
  }
}).limit(${p.limit})`;
  }

  return `db.businesses.aggregate([
  { $geoNear: {
      near: ${point(p.lon, p.lat)},
      distanceField: "distance_m", maxDistance: ${p.radius}, spherical: true, key: "location",${
        category ? `\n      query: { categories: ${categoryFilter(category)} },` : ""
      }
  } },
  { $project: { business_id: 1, event: 1, days_business: 1, distance_m: 1 } },
  { $lookup: {
      from: "reviews", localField: "business_id", foreignField: "business_id", as: "reviews",
      pipeline: [{ $group: { _id: null, n: { $sum: 1 }, stars: { $sum: "$stars" },
        negative: { $sum: { $cond: [{ $lte: ["$stars", 2] }, 1, 0] } },
        neutral:  { $sum: { $cond: [{ $eq:  ["$stars", 3] }, 1, 0] } },
        positive: { $sum: { $cond: [{ $gte: ["$stars", 4] }, 1, 0] } } } }],
  } },
  { $unwind: { path: "$reviews", preserveNullAndEmptyArrays: true } },
  { $group: { _id: null, n_businesses: { $sum: 1 }, closures: { $sum: "$event" },
      business_days: { $sum: "$days_business" }, n_reviews: { $sum: "$reviews.n" } /* ... */ } },
])
// tasa de cierre = closures / (business_days / 365) * 100   (mínimo ${p.minDays} días-negocio para compararla)`;
}
