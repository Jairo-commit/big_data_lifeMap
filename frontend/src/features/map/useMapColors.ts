import { useEffect, useState } from "react";
import type { Theme } from "@/lib/theme";

export interface MapColors {
  open: string;
  closed: string;
  ring: string;
  shape: string;
}

const FALLBACK: MapColors = { open: "#009e73", closed: "#d55e00", ring: "#ffffff", shape: "#0f766e" };

function read(): MapColors {
  const css = getComputedStyle(document.documentElement);
  const get = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    open: get("--map-point-open", FALLBACK.open),
    closed: get("--map-point-closed", FALLBACK.closed),
    ring: get("--map-point-ring", FALLBACK.ring),
    shape: get("--map-shape", FALLBACK.shape),
  };
}

/** Leaflet dibuja en canvas y el canvas no entiende var(): se leen los tokens ya resueltos del tema activo. */
export function useMapColors(theme: Theme): MapColors {
  const [colors, setColors] = useState<MapColors>(FALLBACK);
  useEffect(() => {
    setColors(read());
  }, [theme]);
  return colors;
}
