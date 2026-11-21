import type { Map as LeafletMap } from "leaflet";
import { Code2, Loader2, MapPinned, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { api, ApiError, type ZoneSummary as ZoneSummaryData } from "@/lib/api";
import { CITIES, DEFAULT_CITY } from "@/lib/cities";
import { fmtInt } from "@/lib/format";
import {
  isValidLat,
  isValidLon,
  polygonFromVertices,
  roundCoord,
  verticesFromBounds,
  zoomForRadius,
  type LatLng,
} from "@/lib/geo";
import type { Theme } from "@/lib/theme";
import { MapCanvas, type ViewTarget } from "./MapCanvas";
import { mongoSnippet } from "./mongo";
import { QueryPanel, type FormErrors, type QueryForm } from "./QueryPanel";
import { ResultsTable } from "./ResultsTable";
import { MODE_META, ZONE_MAX_RADIUS, type QueryMode, type QueryResult } from "./types";
import { ZoneSummary } from "./ZoneSummary";

const INITIAL_FORM: QueryForm = {
  mode: "near",
  lat: String(DEFAULT_CITY.lat),
  lon: String(DEFAULT_CITY.lon),
  radius: "1000",
  category: "",
  limit: String(MODE_META.near.defaultLimit),
  minDays: "3650",
};

function toInt(text: string) {
  return /^\d+$/.test(text.trim()) ? Number(text.trim()) : NaN;
}

export function MapView({ theme }: { theme: Theme }) {
  const [form, setForm] = useState<QueryForm>(INITIAL_FORM);
  const [errors, setErrors] = useState<FormErrors>({});
  const [vertices, setVertices] = useState<LatLng[]>([]);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [zone, setZone] = useState<ZoneSummaryData | null>(null);
  const [loadingBusinesses, setLoadingBusinesses] = useState(false);
  const [loadingZone, setLoadingZone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [fitSignal, setFitSignal] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [viewTarget, setViewTarget] = useState<ViewTarget>({ lat: DEFAULT_CITY.lat, lon: DEFAULT_CITY.lon, zoom: 14, nonce: 0 });

  const mapRef = useRef<LeafletMap | null>(null);
  const controller = useRef<AbortController | null>(null);

  const busy = loadingBusinesses || loadingZone;
  const lat = Number(form.lat);
  const lon = Number(form.lon);
  const center = isValidLat(lat) && isValidLon(lon) && form.lat.trim() !== "" && form.lon.trim() !== "" ? { lat, lon } : null;
  const radius = toInt(form.radius);
  const radiusForMap = Number.isFinite(radius) && radius > 0 ? radius : 1000;

  // Cronómetro visible mientras hay una consulta en curso (el resumen de zona puede tardar decenas de segundos)
  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  useEffect(() => () => controller.current?.abort(), []);

  const change = useCallback((patch: Partial<QueryForm>) => {
    setForm((current) => ({ ...current, ...patch }));
    setErrors((current) => {
      const next = { ...current };
      for (const key of Object.keys(patch)) delete next[key as keyof FormErrors];
      return next;
    });
  }, []);

  function changeMode(mode: QueryMode) {
    setForm((current) => {
      const previousDefault = String(MODE_META[current.mode].defaultLimit);
      return {
        ...current,
        mode,
        limit: current.limit === previousDefault ? String(MODE_META[mode].defaultLimit) : current.limit,
        radius: mode === "zone" && toInt(current.radius) > ZONE_MAX_RADIUS ? "1000" : current.radius,
      };
    });
    setErrors({});
    setResult(null);
    setZone(null);
    setError(null);
  }

  function pick(pickedLat: number, pickedLon: number) {
    if (form.mode === "within") {
      setVertices((current) => [...current, [roundCoord(pickedLat), roundCoord(pickedLon)]]);
      setErrors((current) => ({ ...current, vertices: undefined }));
    } else {
      change({ lat: String(roundCoord(pickedLat)), lon: String(roundCoord(pickedLon)) });
    }
  }

  function goToCity(index: number) {
    const city = CITIES[index];
    if (!city) return;
    change({ lat: String(city.lat), lon: String(city.lon) });
    setViewTarget((current) => ({ lat: city.lat, lon: city.lon, zoom: zoomForRadius(radiusForMap), nonce: current.nonce + 1 }));
  }

  function useViewport() {
    const bounds = mapRef.current?.getBounds();
    if (!bounds) return;
    setVertices(
      verticesFromBounds({ south: bounds.getSouth(), west: bounds.getWest(), north: bounds.getNorth(), east: bounds.getEast() }).map(
        ([a, b]) => [roundCoord(a), roundCoord(b)] as LatLng,
      ),
    );
    setErrors((current) => ({ ...current, vertices: undefined }));
  }

  function validate() {
    const found: FormErrors = {};
    const meta = MODE_META[form.mode];
    const limit = toInt(form.limit);
    const minDays = toInt(form.minDays);

    if (form.mode === "within") {
      if (vertices.length < 3) found.vertices = "Añade al menos 3 vértices: haz clic en el mapa o usa el área visible.";
    } else {
      if (!isValidLat(lat) || form.lat.trim() === "") found.lat = "Latitud entre −90 y 90.";
      if (!isValidLon(lon) || form.lon.trim() === "") found.lon = "Longitud entre −180 y 180.";
      if (!(radius >= 1 && radius <= 50000)) found.radius = "Un número entero entre 1 y 50 000.";
      else if (form.mode === "zone" && radius > ZONE_MAX_RADIUS) {
        found.radius = `El resumen de zona admite hasta ${fmtInt(ZONE_MAX_RADIUS)} m: con más radio la agregación tarda minutos.`;
      }
    }
    if (!(limit >= 1 && limit <= meta.maxLimit)) found.limit = `Un número entre 1 y ${meta.maxLimit}.`;
    if (form.mode === "zone" && !(minDays >= 0)) found.minDays = "Un número entero, 0 o más.";

    setErrors(found);
    return Object.keys(found).length === 0;
  }

  async function run() {
    if (!validate()) return;
    controller.current?.abort();
    const ctrl = new AbortController();
    controller.current = ctrl;

    const category = form.category.trim() || undefined;
    const limit = toInt(form.limit);
    const started = performance.now();
    const elapsedMs = () => Math.round(performance.now() - started);

    setError(null);
    setResult(null);
    setZone(null);
    setHovered(null);
    setLoadingBusinesses(true);
    setLoadingZone(form.mode === "zone");

    const fail = (reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof ApiError ? reason.message : "Error inesperado al consultar la API.");
    };

    try {
      if (form.mode === "within") {
        const polygon = polygonFromVertices(vertices);
        if (!polygon) return;
        const response = await api.within(polygon, { category, limit }, ctrl.signal);
        setResult({ mode: "within", total: response.total, returned: response.returned, elapsedMs: elapsedMs(), businesses: response.businesses });
        setFitSignal((n) => n + 1);
      } else {
        const circle = { lat, lon, radius, category };
        const businessesRequest = api.near({ ...circle, limit }, ctrl.signal).then((response) => {
          setResult({ mode: form.mode, total: null, returned: response.returned, elapsedMs: elapsedMs(), businesses: response.businesses });
          setFitSignal((n) => n + 1);
        });
        const zoneRequest =
          form.mode === "zone"
            ? api
                .zone({ ...circle, min_days: toInt(form.minDays) }, ctrl.signal)
                .then(setZone)
                .finally(() => setLoadingZone(false))
            : Promise.resolve();
        // Los negocios llegan primero (es rápido); el resumen aparece cuando termina su agregación
        await Promise.all([businessesRequest.finally(() => setLoadingBusinesses(false)), zoneRequest]);
      }
    } catch (reason) {
      fail(reason);
    } finally {
      if (controller.current === ctrl) {
        setLoadingBusinesses(false);
        setLoadingZone(false);
      }
    }
  }

  function cancel() {
    controller.current?.abort();
    setLoadingBusinesses(false);
    setLoadingZone(false);
  }

  const snippet = useMemo(() => {
    const polygon = polygonFromVertices(vertices);
    return mongoSnippet(form.mode, {
      lon: center?.lon ?? 0,
      lat: center?.lat ?? 0,
      radius: radiusForMap,
      category: form.category,
      limit: toInt(form.limit) || MODE_META[form.mode].defaultLimit,
      minDays: toInt(form.minDays) || 3650,
      polygon,
    });
  }, [form, vertices, center?.lat, center?.lon, radiusForMap]);

  const meta = MODE_META[form.mode];
  const shown = result?.businesses ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-[23rem_minmax(0,1fr)]">
      <Card aria-labelledby="query-title" className="lg:sticky lg:top-20 lg:max-h-[calc(100dvh-6rem)] lg:self-start lg:overflow-y-auto">
        <CardHeader id="query-title" title="Consulta geoespacial" description="Se ejecuta sobre MongoDB (índice 2dsphere) a través de la API." />
        <CardContent>
          <QueryPanel
            form={form}
            errors={errors}
            vertexCount={vertices.length}
            busy={busy}
            onChange={change}
            onModeChange={changeMode}
            onCity={goToCity}
            onUseViewport={useViewport}
            onUndoVertex={() => setVertices((v) => v.slice(0, -1))}
            onClearShape={() => setVertices([])}
            onRun={run}
          />
        </CardContent>
      </Card>

      <div className="min-w-0 space-y-4">
        <div className="relative h-[24rem] overflow-hidden rounded-[var(--card-radius)] border border-border shadow-[var(--card-shadow)] sm:h-[32rem] lg:h-[34rem]">
          <MapCanvas
            theme={theme}
            mode={form.mode}
            center={center}
            radius={radiusForMap}
            vertices={vertices}
            businesses={shown}
            highlightedId={hovered}
            onHover={setHovered}
            onPick={pick}
            mapRef={mapRef}
            viewTarget={viewTarget}
            fitSignal={fitSignal}
          />

          {busy ? (
            <div role="status" className="absolute left-1/2 top-3 z-[1000] flex -translate-x-1/2 items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-sm shadow-[var(--shadow-popover)]">
              <Loader2 className="size-4 animate-spin text-primary" aria-hidden="true" />
              <span>Consultando…</span>
              <span className="tnum text-muted-foreground" aria-hidden="true">
                {elapsed} s
              </span>
              <Button size="sm" variant="ghost" onClick={cancel} className="-mr-1 h-7">
                <X aria-hidden="true" /> Cancelar
              </Button>
            </div>
          ) : null}

          <ul className="absolute bottom-6 left-3 z-[1000] space-y-1 rounded-md border border-border bg-card/95 px-3 py-2 text-xs shadow-[var(--shadow-card)]" aria-label="Leyenda del mapa">
            <li className="flex items-center gap-2">
              <span aria-hidden="true" className="inline-block size-3 rounded-full bg-open ring-2 ring-card" /> Negocio abierto (punto relleno)
            </li>
            <li className="flex items-center gap-2">
              <span aria-hidden="true" className="inline-block size-3 rounded-full border-2 border-closed bg-closed/10" /> Negocio cerrado (punto hueco)
            </li>
          </ul>
        </div>

        {error ? (
          <div role="alert" className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive-surface px-4 py-3 text-sm text-destructive">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <div>
              <p className="font-medium">No se pudo completar la consulta</p>
              <p>{error}</p>
            </div>
          </div>
        ) : null}

        {form.mode === "zone" && (loadingZone || zone) ? <ZoneSummary loading={loadingZone} data={zone} /> : null}

        {result ? (
          <Card aria-labelledby="results-title">
            <CardHeader
              id="results-title"
              as="h3"
              title={
                result.total != null
                  ? `${fmtInt(result.returned)} de ${fmtInt(result.total)} negocios dentro del polígono`
                  : `${fmtInt(result.returned)} ${result.returned === 1 ? "negocio" : "negocios"} encontrados`
              }
              description={`${meta.operator} · ${fmtInt(result.elapsedMs)} ms${
                result.total == null && result.returned === toInt(form.limit) ? " · es el límite: puede haber más, los más lejanos no se muestran" : ""
              }`}
            />
            <CardContent>
              {result.returned === 0 ? (
                <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
                  Ningún negocio cumple la consulta. Prueba con otro punto, un radio mayor o sin categoría.
                </p>
              ) : (
                <ResultsTable businesses={result.businesses} highlightedId={hovered} onHover={setHovered} showDistance={result.mode !== "within"} />
              )}
            </CardContent>
          </Card>
        ) : !busy && !error ? (
          <Card>
            <CardContent className="flex items-center gap-3 pt-5 text-sm text-muted-foreground">
              <MapPinned className="size-5 shrink-0 text-primary" aria-hidden="true" />
              Elige el tipo de consulta, marca un punto o un polígono en el mapa y pulsa «Ejecutar consulta». Los negocios aparecerán como puntos: pasa el cursor sobre uno para ver su ficha.
            </CardContent>
          </Card>
        ) : null}

        <details className="group rounded-[var(--card-radius)] border border-border bg-card px-5 py-3 shadow-[var(--card-shadow)]">
          <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium">
            <Code2 className="size-4 text-primary" aria-hidden="true" /> Consulta de MongoDB equivalente ({meta.operator})
          </summary>
          <pre className="mt-3 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
            <code>{snippet}</code>
          </pre>
        </details>
      </div>
    </div>
  );
}
