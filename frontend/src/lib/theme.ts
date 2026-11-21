import { useCallback, useEffect, useLayoutEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "lifemap-theme";

function systemTheme(): Theme {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function initialTheme(): Theme {
  const attr = document.documentElement.dataset.theme;
  return attr === "light" || attr === "dark" ? attr : systemTheme();
}

/** Tema efectivo (el guardado o, si no hay, el del sistema) y una función para alternarlo. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  // useLayoutEffect: el atributo debe estar puesto antes de que los hijos lean los tokens ya resueltos
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Sin preferencia guardada, seguir los cambios del sistema
  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(KEY);
    } catch {
      /* sin almacenamiento: se sigue al sistema */
    }
    if (saved) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setTheme(query.matches ? "dark" : "light");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* el tema sigue funcionando sin guardarse */
      }
      return next;
    });
  }, []);

  return { theme, toggle };
}
