/** Clases de color del modelo: el elegido como mejor usa el color de marca y el otro el secundario. */
export const modelSwatch = (isBest: boolean) => (isBest ? "bg-model-best" : "bg-model-other");

export const CLASS_BAR: Record<string, string> = {
  negativo: "bg-negative",
  neutral: "bg-neutral",
  positivo: "bg-positive",
};
