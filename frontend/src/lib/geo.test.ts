import { describe, expect, it } from "vitest";
import { boundsAround, isValidLat, isValidLon, polygonFromVertices, roundCoord, verticesFromBounds, zoomForRadius } from "./geo";

describe("polygonFromVertices", () => {
  it("con menos de 3 vértices no hay polígono", () => {
    expect(polygonFromVertices([])).toBeNull();
    expect(polygonFromVertices([[1, 2], [3, 4]])).toBeNull();
  });

  it("pasa de (lat, lon) a GeoJSON (lon, lat) y cierra el anillo", () => {
    const polygon = polygonFromVertices([[10, 20], [10, 21], [11, 21]]);
    expect(polygon?.coordinates[0]).toEqual([[20, 10], [21, 10], [21, 11], [20, 10]]);
  });
});

describe("verticesFromBounds", () => {
  it("da las cuatro esquinas del área visible", () => {
    expect(verticesFromBounds({ south: 1, west: 2, north: 3, east: 4 })).toEqual([[1, 2], [1, 4], [3, 4], [3, 2]]);
  });
});

describe("validación de coordenadas", () => {
  it("acepta los rangos válidos y rechaza el resto", () => {
    expect(isValidLat(90)).toBe(true);
    expect(isValidLat(90.1)).toBe(false);
    expect(isValidLon(-180)).toBe(true);
    expect(isValidLon(Number.NaN)).toBe(false);
  });
});

describe("roundCoord y zoomForRadius", () => {
  it("redondea a 5 decimales", () => {
    expect(roundCoord(39.123456789)).toBe(39.12346);
  });

  it("más radio, menos zoom", () => {
    expect(zoomForRadius(300)).toBeGreaterThan(zoomForRadius(5000));
  });
});

describe("boundsAround", () => {
  it("rodea el punto con medio lado igual al radio", () => {
    const [sw, ne] = boundsAround(0, 0, 111_320);
    expect(sw[0]).toBeCloseTo(-1, 5);
    expect(ne[0]).toBeCloseTo(1, 5);
    expect(ne[1]).toBeCloseTo(1, 5);
  });

  it("lejos del ecuador la caja es más ancha en grados de longitud", () => {
    const [swEq, neEq] = boundsAround(0, 0, 1000);
    const [sw60, ne60] = boundsAround(60, 0, 1000);
    expect(ne60[1] - sw60[1]).toBeGreaterThan(neEq[1] - swEq[1]);
  });
});
