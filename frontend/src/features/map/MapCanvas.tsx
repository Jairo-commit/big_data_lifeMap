import { latLngBounds, type Map as LeafletMap } from "leaflet";
import { useEffect, type RefObject } from "react";
import { Circle, CircleMarker, MapContainer, Polygon, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { Business } from "@/lib/api";
import { boundsAround, type LatLng } from "@/lib/geo";
import type { Theme } from "@/lib/theme";
import { BusinessInfo } from "./BusinessInfo";
import type { QueryMode } from "./types";
import { useMapColors } from "./useMapColors";

export interface ViewTarget {
  lat: number;
  lon: number;
  zoom: number;
  /** Cambia en cada orden de mover la vista, aunque el destino sea el mismo. */
  nonce: number;
}

interface MapCanvasProps {
  theme: Theme;
  mode: QueryMode;
  center: { lat: number; lon: number } | null;
  radius: number;
  vertices: LatLng[];
  businesses: Business[];
  highlightedId: string | null;
  onHover: (id: string | null) => void;
  onPick: (lat: number, lon: number) => void;
  mapRef: RefObject<LeafletMap | null>;
  viewTarget: ViewTarget;
  /** Cambia cuando llegan resultados nuevos: el mapa se encuadra sobre ellos. */
  fitSignal: number;
}

// Teselas de OpenStreetMap (sin clave). En el tema oscuro se invierten con un filtro CSS (.lm-tiles-dark)
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

function PickHandler({ onPick }: { onPick: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (event) => onPick(event.latlng.lat, event.latlng.lng) });
  return null;
}

function ViewController({ target }: { target: ViewTarget }) {
  const map = useMap();
  useEffect(() => {
    map.setView([target.lat, target.lon], target.zoom, { animate: true });
  }, [map, target]);
  return null;
}

interface FitProps {
  signal: number;
  businesses: Business[];
  center: { lat: number; lon: number } | null;
  radius: number;
  vertices: LatLng[];
  mode: QueryMode;
}

function FitController({ signal, businesses, center, radius, vertices, mode }: FitProps) {
  const map = useMap();
  useEffect(() => {
    if (signal === 0) return;
    const points: [number, number][] = businesses.map((b) => [b.location.coordinates[1], b.location.coordinates[0]]);
    if (mode === "within") {
      points.push(...vertices);
    } else if (center) {
      points.push(...boundsAround(center.lat, center.lon, radius));
    }
    if (points.length === 0) return;
    map.fitBounds(latLngBounds(points).pad(0.08), { maxZoom: 17, animate: true });
    // Solo se reencuadra cuando llegan resultados nuevos, no al mover el centro o el radio
  }, [signal]);
  return null;
}

export function MapCanvas({
  theme,
  mode,
  center,
  radius,
  vertices,
  businesses,
  highlightedId,
  onHover,
  onPick,
  mapRef,
  viewTarget,
  fitSignal,
}: MapCanvasProps) {
  const colors = useMapColors(theme);
  const highlighted = businesses.find((b) => b.business_id === highlightedId);
  const shape = { color: colors.shape, weight: 2 };

  return (
    <MapContainer
      ref={mapRef}
      center={[viewTarget.lat, viewTarget.lon]}
      zoom={viewTarget.zoom}
      preferCanvas
      scrollWheelZoom
      className="h-full w-full cursor-crosshair"
      aria-label="Mapa de negocios. Haz clic para fijar el punto de la consulta o añadir vértices al polígono."
    >
      <TileLayer
        url={TILE_URL}
        maxZoom={19}
        className={theme === "dark" ? "lm-tiles lm-tiles-dark" : "lm-tiles"}
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      />
      <PickHandler onPick={onPick} />
      <ViewController target={viewTarget} />
      <FitController
        signal={fitSignal}
        businesses={businesses}
        center={center}
        radius={radius}
        vertices={vertices}
        mode={mode}
      />

      {/* Forma de la consulta */}
      {mode !== "within" && center ? (
        <>
          <Circle
            center={[center.lat, center.lon]}
            radius={radius}
            pathOptions={{ ...shape, fillColor: colors.shape, fillOpacity: 0.07, dashArray: "6 6" }}
            interactive={false}
          />
          <CircleMarker
            center={[center.lat, center.lon]}
            radius={6}
            pathOptions={{ color: colors.ring, weight: 2, fillColor: colors.shape, fillOpacity: 1 }}
            interactive={false}
          />
        </>
      ) : null}

      {mode === "within" && vertices.length >= 3 ? (
        <Polygon
          positions={vertices}
          pathOptions={{ ...shape, fillColor: colors.shape, fillOpacity: 0.08, dashArray: "6 6" }}
          interactive={false}
        />
      ) : null}
      {mode === "within" && vertices.length === 2 ? (
        <Polyline positions={vertices} pathOptions={{ ...shape, dashArray: "6 6" }} interactive={false} />
      ) : null}
      {mode === "within"
        ? vertices.map((vertex, index) => (
            <CircleMarker
              key={`${vertex[0]}-${vertex[1]}-${index}`}
              center={vertex}
              radius={5}
              pathOptions={{ color: colors.ring, weight: 2, fillColor: colors.shape, fillOpacity: 1 }}
              interactive={false}
            />
          ))
        : null}

      {/* Negocios de la consulta: relleno = abierto, hueco = cerrado (el color nunca va solo) */}
      {businesses.map((business) => {
        const [lon, lat] = business.location.coordinates;
        const isOpen = business.is_open === 1;
        const color = isOpen ? colors.open : colors.closed;
        return (
          <CircleMarker
            key={business.business_id}
            center={[lat, lon]}
            radius={isOpen ? 6 : 6.5}
            pathOptions={{
              color: isOpen ? colors.ring : color,
              weight: isOpen ? 1.5 : 2.5,
              fillColor: color,
              fillOpacity: isOpen ? 0.9 : 0.12,
            }}
            eventHandlers={{
              mouseover: () => onHover(business.business_id),
              mouseout: () => onHover(null),
            }}
          >
            <Tooltip sticky direction="top" offset={[0, -8]} opacity={1} className="lm-tooltip">
              <BusinessInfo business={business} />
            </Tooltip>
          </CircleMarker>
        );
      })}

      {highlighted ? (
        <CircleMarker
          center={[highlighted.location.coordinates[1], highlighted.location.coordinates[0]]}
          radius={12}
          pathOptions={{ color: colors.shape, weight: 3, fillOpacity: 0 }}
          interactive={false}
        />
      ) : null}
    </MapContainer>
  );
}
