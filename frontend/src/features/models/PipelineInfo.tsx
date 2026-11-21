import { Card, CardContent, CardHeader } from "@/components/ui/card";

const STEPS = [
  { title: "Etiqueta", text: "Se deriva de las estrellas: 1-2 negativo, 3 neutral, 4-5 positivo." },
  { title: "Limpieza", text: "Minúsculas, sin URLs y solo letras." },
  { title: "Tokenización", text: "Palabras de al menos 2 letras, sin las stopwords en inglés." },
  { title: "Vectorización", text: "HashingTF con 262 144 (2^18) características y luego IDF (frecuencia mínima de documento: 5)." },
  { title: "Clasificadores", text: "Naive Bayes multinomial y regresión logística multinomial (20 iteraciones)." },
  { title: "Desbalance", text: "Pesos de clase inversos a su frecuencia, para que las clases pequeñas cuenten." },
  { title: "Partición", text: "80 % de los negocios para entrenar y 20 % para evaluar, decidido por el hash del business_id: ninguno queda en los dos lados." },
  { title: "Selección", text: "Se guarda como mejor el de mayor F1 macro; ese es el que usa /predict." },
];

export function PipelineInfo() {
  return (
    <Card aria-labelledby="pipeline-title">
      <CardHeader id="pipeline-title" title="Cómo se entrenó" description="Pipeline de Spark MLlib guardado completo: acepta texto crudo y no se reentrena para predecir." />
      <CardContent>
        <ol className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {STEPS.map((step, index) => (
            <li key={step.title} className="flex gap-3 text-sm">
              <span aria-hidden="true" className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground tnum">
                {index + 1}
              </span>
              <span>
                <strong className="font-medium">{step.title}.</strong> <span className="text-muted-foreground">{step.text}</span>
              </span>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
