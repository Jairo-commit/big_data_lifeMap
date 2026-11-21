import { useEffect, useState } from "react";

export type Route = "mapa" | "modelos";
export const ROUTES: Route[] = ["mapa", "modelos"];

function parse(hash: string): Route {
  const name = hash.replace(/^#\/?/, "");
  return (ROUTES as string[]).includes(name) ? (name as Route) : "mapa";
}

/** Enrutado por hash (#/mapa, #/modelos): cada vista tiene su propia URL y funciona el botón Atrás. */
export function useRoute() {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return route;
}

export const hrefFor = (route: Route) => `#/${route}`;
