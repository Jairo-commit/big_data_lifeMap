import type { LonLat, PolygonGeometry } from "./api";

export type LatLng = [number, number];

export interface Bounds {
  south: number;
  west: number;
  north: number;
  east: number;
}

/** Los vértices que se dibujan en el mapa (lat, lon) → anillo GeoJSON cerrado (lon, lat). */
export function polygonFromVertices(vertices: LatLng[]): PolygonGeometry | null {
  if (vertices.length < 3) return null;
  const ring: LonLat[] = vertices.map(([lat, lon]) => [lon, lat]);
  const first = ring[0] as LonLat;
  ring.push([first[0], first[1]]);
  return { type: "Polygon", coordinates: [ring] };
}

/** Rectángulo con el área visible del mapa, para consultar "lo que estoy viendo". */
export function verticesFromBounds({ south, west, north, east }: Bounds): LatLng[] {
  return [
    [south, west],
    [south, east],
    [north, east],
    [north, west],
  ];
}

export function isValidLat(value: number) {
  return Number.isFinite(value) && value >= -90 && value <= 90;
}

export function isValidLon(value: number) {
  return Number.isFinite(value) && value >= -180 && value <= 180;
}

export function roundCoord(value: number, digits = 5) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/** Zoom de Leaflet que deja un radio (m) razonablemente visible. */
export function zoomForRadius(radiusMeters: number) {
  if (radiusMeters <= 300) return 16;
  if (radiusMeters <= 800) return 15;
  if (radiusMeters <= 2000) return 14;
  if (radiusMeters <= 5000) return 12;
  if (radiusMeters <= 15000) return 11;
  return 9;
}

const METERS_PER_DEGREE_LAT = 111_320;

/** Esquinas (sur-oeste y norte-este) de la caja que rodea un círculo; sirve para encuadrar el mapa sin dibujarlo. */
export function boundsAround(lat: number, lon: number, radiusMeters: number): [LatLng, LatLng] {
  const dLat = radiusMeters / METERS_PER_DEGREE_LAT;
  const dLon = radiusMeters / (METERS_PER_DEGREE_LAT * Math.max(Math.cos((lat * Math.PI) / 180), 0.01));
  return [
    [lat - dLat, lon - dLon],
    [lat + dLat, lon + dLon],
  ];
}
