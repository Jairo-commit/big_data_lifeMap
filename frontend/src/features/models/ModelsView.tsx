import { TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import { api, ApiError, type ModelsInfo } from "@/lib/api";
import { fmtCompact, fmtDate, fmtInt, modelLabel } from "@/lib/format";
import { ClassDistribution } from "./ClassDistribution";
import { ClassMetricsChart } from "./ClassMetricsChart";
import { ConfusionMatrices } from "./ConfusionMatrix";
import { ModelComparison } from "./ModelComparison";
import { PipelineInfo } from "./PipelineInfo";
import { TryIt } from "./TryIt";

type State =
  | { status: "loading" }
  | { status: "empty"; detail: string }
  | { status: "error"; message: string }
  | { status: "ready"; info: ModelsInfo };

function Skeleton() {
  return (
    <div aria-hidden="true" className="space-y-4">
      <div className="h-28 animate-pulse rounded-[var(--card-radius)] bg-muted" />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="h-64 animate-pulse rounded-[var(--card-radius)] bg-muted" />
        <div className="h-64 animate-pulse rounded-[var(--card-radius)] bg-muted" />
      </div>
    </div>
  );
}

export function ModelsView() {
  const [state, setState] = useState<State>({ status: "loading" });

  const load = useCallback((signal?: AbortSignal) => {
    setState({ status: "loading" });
    api
      .models(signal)
      .then((info) => setState({ status: "ready", info }))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (reason instanceof ApiError && reason.code === "models_not_available") setState({ status: "empty", detail: reason.message });
        else if (reason instanceof ApiError && reason.status === 404) {
          setState({ status: "error", message: "Esta versión de la API no tiene el endpoint /models: hace falta desplegar la versión nueva." });
        } else setState({ status: "error", message: reason instanceof ApiError ? reason.message : "No se pudieron cargar los modelos." });
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (state.status === "loading") {
    return (
      <div role="status" aria-label="Cargando los modelos">
        <Skeleton />
      </div>
    );
  }

  if (state.status === "empty") {
    return (
      <Card>
        <CardContent className="pt-5">
          <h2 className="text-base font-semibold">Aún no hay modelos entrenados</h2>
          <p className="mt-1 text-sm text-muted-foreground">{state.detail}</p>
        </CardContent>
      </Card>
    );
  }

  if (state.status === "error") {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/40 bg-destructive-surface px-4 py-3 text-sm text-destructive">
        <TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
        <p className="flex-1">{state.message}</p>
        <Button size="sm" variant="outline" onClick={() => load()}>
          Reintentar
        </Button>
      </div>
    );
  }

  const { info } = state;
  return (
    <div className="space-y-4">
      <Card aria-label="Resumen del entrenamiento">
        <CardContent className="pt-5">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 lg:grid-cols-4">
            <Stat label="Reseñas usadas" value={fmtCompact(info.reviews)} hint={`${fmtInt(info.reviews)} en total${info.sample_fraction != null && info.sample_fraction < 1 ? ` (muestra del ${Math.round(info.sample_fraction * 100)} %)` : ""}`} />
            <Stat label="Modelos comparados" value={Object.keys(info.models).length} hint={Object.keys(info.models).map(modelLabel).join(" y ")} />
            <Stat label="Mejor modelo" value={<span className="text-xl">{modelLabel(info.best_model)}</span>} hint="Por F1 macro" />
            <Stat label="Entrenado" value={<span className="text-base">{fmtDate(info.trained_at)}</span>} hint={info.cutoff ? `Reseñas hasta ${info.cutoff}` : "Todas las reseñas, sin fecha de corte"} />
          </dl>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <ClassDistribution distribution={info.class_distribution} classes={info.classes} total={info.reviews} />
        <ModelComparison info={info} />
      </div>

      <ClassMetricsChart info={info} />
      <ConfusionMatrices info={info} />

      <div className="grid gap-4 xl:grid-cols-2">
        <TryIt bestModel={info.best_model} />
        <PipelineInfo />
      </div>
    </div>
  );
}
