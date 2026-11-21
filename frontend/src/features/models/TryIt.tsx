import { Sparkles } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Field, Textarea } from "@/components/ui/form";
import { api, ApiError, type Prediction } from "@/lib/api";
import { classLabel, fmtPercent, modelLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CLASS_BAR } from "./shared";

// El modelo se entrenó con reseñas de Yelp en inglés
const EXAMPLES = [
  { label: "Positiva", text: "The food was amazing and the staff were incredibly friendly. We will definitely come back!" },
  { label: "Negativa", text: "Terrible service, cold food and a long wait. I will never come back to this place." },
  { label: "Neutral", text: "It was okay. Nothing special, but not bad either." },
];

const MAX_LENGTH = 10_000;

export function TryIt({ bestModel }: { bestModel: string }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const controller = useRef<AbortController | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) {
      setError("Escribe una reseña para clasificar.");
      return;
    }
    controller.current?.abort();
    const ctrl = new AbortController();
    controller.current = ctrl;
    setLoading(true);
    setError(null);
    try {
      setPrediction(await api.predict(text, ctrl.signal));
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setPrediction(null);
      setError(reason instanceof ApiError ? reason.message : "No se pudo clasificar el texto.");
    } finally {
      if (controller.current === ctrl) setLoading(false);
    }
  }

  const ranked = prediction ? Object.entries(prediction.probabilities).sort((a, b) => b[1] - a[1]) : [];

  return (
    <Card aria-labelledby="tryit-title">
      <CardHeader
        id="tryit-title"
        title="Pruébalo con una reseña"
        description={`Clasifica un texto con el modelo guardado como mejor (${modelLabel(bestModel)}). Entrenado con reseñas en inglés.`}
      />
      <CardContent className="space-y-4">
        <form onSubmit={submit} className="space-y-3" noValidate>
          <Field id="review-text" label="Reseña" error={error} hint={`${text.length.toLocaleString("es-CO")} / ${MAX_LENGTH.toLocaleString("es-CO")} caracteres`}>
            <Textarea
              id="review-text"
              value={text}
              maxLength={MAX_LENGTH}
              onChange={(event) => {
                setText(event.target.value);
                setError(null);
              }}
              placeholder="Escribe una reseña en inglés…"
              aria-invalid={!!error}
              aria-describedby={`review-text-hint${error ? " review-text-error" : ""}`}
            />
          </Field>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" loading={loading}>
              {loading ? null : <Sparkles aria-hidden="true" />}
              {loading ? "Clasificando…" : "Clasificar"}
            </Button>
            <span className="text-sm text-muted-foreground">o prueba un ejemplo:</span>
            {EXAMPLES.map((example) => (
              <Button
                key={example.label}
                size="sm"
                variant="outline"
                onClick={() => {
                  setText(example.text);
                  setError(null);
                }}
              >
                {example.label}
              </Button>
            ))}
          </div>
        </form>

        {prediction ? (
          <div aria-live="polite" className="space-y-3 rounded-md border border-border bg-muted/50 p-4">
            <p className="text-sm">
              Clasificación: <strong className="text-base">{classLabel(prediction.sentiment)}</strong>
            </p>
            <ul className="space-y-2">
              {ranked.map(([name, probability]) => (
                <li key={name} className="grid grid-cols-[5.5rem_1fr_3.5rem] items-center gap-3 text-sm">
                  <span className={cn(name === prediction.sentiment && "font-semibold")}>{classLabel(name)}</span>
                  <span className="h-2.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                    <span className={cn("block h-full rounded-full", CLASS_BAR[name] ?? "bg-neutral")} style={{ width: `${probability * 100}%` }} />
                  </span>
                  <span className="text-right tnum">{fmtPercent(probability * 100, 1)}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
