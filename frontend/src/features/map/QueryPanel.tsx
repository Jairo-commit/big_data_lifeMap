import { Crosshair, Eraser, Maximize, Pentagon, Play, Radar, Undo2 } from "lucide-react";
import type { FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Segmented, type SegmentedOption } from "@/components/ui/segmented";
import { CITIES } from "@/lib/cities";
import { MODE_META, ZONE_MAX_RADIUS, type QueryMode } from "./types";

export interface QueryForm {
  mode: QueryMode;
  lat: string;
  lon: string;
  radius: string;
  category: string;
  limit: string;
  minDays: string;
}

export type FormErrors = Partial<Record<keyof QueryForm | "vertices", string>>;

interface QueryPanelProps {
  form: QueryForm;
  errors: FormErrors;
  vertexCount: number;
  busy: boolean;
  onChange: (patch: Partial<QueryForm>) => void;
  onModeChange: (mode: QueryMode) => void;
  onCity: (index: number) => void;
  onUseViewport: () => void;
  onUndoVertex: () => void;
  onClearShape: () => void;
  onRun: () => void;
}

const MODE_OPTIONS: SegmentedOption<QueryMode>[] = [
  { value: "near", label: MODE_META.near.label, hint: `${MODE_META.near.operator} · ${MODE_META.near.hint}`, icon: <Crosshair className="size-4 shrink-0" aria-hidden="true" /> },
  { value: "within", label: MODE_META.within.label, hint: `${MODE_META.within.operator} · ${MODE_META.within.hint}`, icon: <Pentagon className="size-4 shrink-0" aria-hidden="true" /> },
  { value: "zone", label: MODE_META.zone.label, hint: `${MODE_META.zone.operator} · ${MODE_META.zone.hint}`, icon: <Radar className="size-4 shrink-0" aria-hidden="true" /> },
];

const RADIUS_PRESETS = [300, 1000, 2000, 5000];

export function QueryPanel({
  form,
  errors,
  vertexCount,
  busy,
  onChange,
  onModeChange,
  onCity,
  onUseViewport,
  onUndoVertex,
  onClearShape,
  onRun,
}: QueryPanelProps) {
  const meta = MODE_META[form.mode];
  const isCircle = form.mode !== "within";

  function submit(event: FormEvent) {
    event.preventDefault();
    onRun();
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <Segmented legend="Tipo de consulta" layout="stack" value={form.mode} onChange={onModeChange} options={MODE_OPTIONS} />

      <div className="space-y-1.5">
        <label htmlFor="city" className="block text-sm font-medium">
          Ir a una ciudad
        </label>
        <select
          id="city"
          defaultValue=""
          onChange={(event) => {
            if (event.target.value !== "") onCity(Number(event.target.value));
            event.target.value = "";
          }}
          className="h-10 w-full rounded-[var(--input-radius)] border border-[var(--input-border)] bg-[var(--input-bg)] px-3 text-sm pointer-coarse:h-11"
        >
          <option value="" disabled>
            Elige una ciudad…
          </option>
          {CITIES.map((city, index) => (
            <option key={city.name} value={index}>
              {city.name}, {city.state}
            </option>
          ))}
        </select>
      </div>

      {isCircle ? (
        <fieldset className="space-y-3">
          <legend className="mb-1 text-sm font-medium">Centro y radio</legend>
          <p className="text-xs text-muted-foreground">Haz clic en el mapa para fijar el centro, o escribe las coordenadas.</p>
          <div className="grid grid-cols-2 gap-3">
            <Field id="lat" label="Latitud" error={errors.lat}>
              <Input id="lat" inputMode="decimal" value={form.lat} onChange={(e) => onChange({ lat: e.target.value })} aria-invalid={!!errors.lat} aria-describedby={errors.lat ? "lat-error" : undefined} />
            </Field>
            <Field id="lon" label="Longitud" error={errors.lon}>
              <Input id="lon" inputMode="decimal" value={form.lon} onChange={(e) => onChange({ lon: e.target.value })} aria-invalid={!!errors.lon} aria-describedby={errors.lon ? "lon-error" : undefined} />
            </Field>
          </div>
          <Field
            id="radius"
            label="Radio (metros)"
            error={errors.radius}
            hint={form.mode === "zone" ? "Hasta 2 000 m: el resumen suma las reseñas de cada negocio, 500 m tarda unos 7 s y 2 km unos 30 s." : "Entre 1 y 50 000 m."}
          >
            <Input id="radius" inputMode="numeric" value={form.radius} onChange={(e) => onChange({ radius: e.target.value })} aria-invalid={!!errors.radius} aria-describedby={`radius-hint${errors.radius ? " radius-error" : ""}`} />
            <div className="flex flex-wrap gap-1.5 pt-1" role="group" aria-label="Radios habituales">
              {RADIUS_PRESETS.filter((r) => form.mode !== "zone" || r <= ZONE_MAX_RADIUS).map((r) => (
                <Button key={r} size="sm" variant={form.radius === String(r) ? "primary" : "outline"} onClick={() => onChange({ radius: String(r) })}>
                  {r >= 1000 ? `${r / 1000} km` : `${r} m`}
                </Button>
              ))}
            </div>
          </Field>
        </fieldset>
      ) : (
        <fieldset className="space-y-3">
          <legend className="mb-1 text-sm font-medium">Polígono</legend>
          <p className="text-xs text-muted-foreground">
            Haz clic en el mapa para añadir vértices (mínimo 3), o usa el área que estás viendo.
          </p>
          <p className="text-sm tnum" aria-live="polite">
            {vertexCount} {vertexCount === 1 ? "vértice" : "vértices"}
          </p>
          {errors.vertices ? (
            <p role="alert" className="text-xs font-medium text-destructive">
              {errors.vertices}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={onUseViewport}>
              <Maximize aria-hidden="true" /> Usar el área visible
            </Button>
            <Button size="sm" variant="ghost" onClick={onUndoVertex} disabled={vertexCount === 0}>
              <Undo2 aria-hidden="true" /> Deshacer
            </Button>
            <Button size="sm" variant="ghost" onClick={onClearShape} disabled={vertexCount === 0}>
              <Eraser aria-hidden="true" /> Limpiar
            </Button>
          </div>
        </fieldset>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Field id="category" label="Categoría" className="col-span-2" hint="Opcional. Categoría completa de Yelp, p. ej. Pizza, Coffee & Tea, Bars.">
          <Input id="category" value={form.category} onChange={(e) => onChange({ category: e.target.value })} placeholder="Pizza" aria-describedby="category-hint" />
        </Field>
        <Field id="limit" label="Máx. negocios" error={errors.limit} hint={`Hasta ${meta.maxLimit}.`}>
          <Input id="limit" inputMode="numeric" value={form.limit} onChange={(e) => onChange({ limit: e.target.value })} aria-invalid={!!errors.limit} aria-describedby={`limit-hint${errors.limit ? " limit-error" : ""}`} />
        </Field>
        {form.mode === "zone" ? (
          <Field id="minDays" label="Mín. días-negocio" error={errors.minDays} hint="Para comparar tasas.">
            <Input id="minDays" inputMode="numeric" value={form.minDays} onChange={(e) => onChange({ minDays: e.target.value })} aria-invalid={!!errors.minDays} aria-describedby={`minDays-hint${errors.minDays ? " minDays-error" : ""}`} />
          </Field>
        ) : null}
      </div>

      <Button type="submit" className="w-full" loading={busy}>
        {busy ? null : <Play aria-hidden="true" />}
        {busy ? "Consultando…" : "Ejecutar consulta"}
      </Button>
    </form>
  );
}
