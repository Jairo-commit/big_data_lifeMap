import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Header } from "@/components/Header";
import { MapView } from "@/features/map/MapView";
import { ModelsView } from "@/features/models/ModelsView";
import { useRoute, type Route } from "@/lib/route";
import { useTheme } from "@/lib/theme";

const TITLES: Record<Route, { title: string; subtitle: string }> = {
  mapa: {
    title: "Negocios en el mapa",
    subtitle: "Consultas geoespaciales de MongoDB sobre el dataset de Yelp: cada negocio es un punto con su ficha.",
  },
  modelos: {
    title: "Modelos de sentimiento",
    subtitle: "Los clasificadores de reseñas que entrenamos con Spark MLlib, sus métricas y una prueba en vivo.",
  },
};

export default function App() {
  const route = useRoute();
  const { theme, toggle } = useTheme();
  const { title, subtitle } = TITLES[route];

  return (
    <>
      <a href="#contenido" className="sr-only-focusable fixed left-3 top-3 z-[2000] rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground">
        Saltar al contenido
      </a>
      <Header route={route} theme={theme} onToggleTheme={toggle} />
      <main id="contenido" tabIndex={-1} className="mx-auto max-w-[1600px] px-4 py-5 md:px-6">
        <div className="mb-4">
          <h1 className="text-2xl font-semibold">{title}</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{subtitle}</p>
        </div>
        <ErrorBoundary key={route}>{route === "mapa" ? <MapView theme={theme} /> : <ModelsView />}</ErrorBoundary>
      </main>
    </>
  );
}
