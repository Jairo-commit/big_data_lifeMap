import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, type Health } from "@/lib/api";
import { hrefFor, ROUTES, type Route } from "@/lib/route";
import type { Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const NAV_LABEL: Record<Route, string> = { mapa: "Mapa", modelos: "Modelos" };

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="size-8 shrink-0" aria-hidden="true">
      <rect width="32" height="32" rx="8" style={{ fill: "var(--primary)" }} />
      <path d="M16 6.5c-4 0-7 3-7 6.9 0 5 7 11.1 7 11.1s7-6.1 7-11.1c0-3.9-3-6.9-7-6.9Z" style={{ fill: "var(--primary-foreground)" }} />
      <circle cx="16" cy="13.4" r="2.6" style={{ fill: "var(--primary)" }} />
    </svg>
  );
}

function HealthPill() {
  const [health, setHealth] = useState<Health | "offline" | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .health(controller.signal)
      .then(setHealth)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setHealth("offline");
      });
    return () => controller.abort();
  }, []);

  if (health === null) return null;
  const ok = health !== "offline" && health.status === "ok";
  const label = health === "offline" ? "API sin conexión" : ok ? "API operativa" : "API con fallos";
  const detail =
    health === "offline"
      ? undefined
      : `${Object.entries(health.services)
          .map(([name, status]) => `${name}: ${status}`)
          .join(" · ")}${health.commit_hash && health.commit_hash !== "unknown" ? ` · commit ${health.commit_hash.slice(0, 7)}` : ""}`;

  return (
    <span title={detail} className="hidden items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs sm:inline-flex">
      <span aria-hidden="true" className={cn("size-2 rounded-full", ok ? "bg-open" : "border-2 border-closed")} />
      {label}
      {health !== "offline" && health.commit_hash && health.commit_hash !== "unknown" ? (
        <span className="font-mono text-muted-foreground">{health.commit_hash.slice(0, 7)}</span>
      ) : null}
    </span>
  );
}

interface HeaderProps {
  route: Route;
  theme: Theme;
  onToggleTheme: () => void;
}

export function Header({ route, theme, onToggleTheme }: HeaderProps) {
  return (
    <header className="sticky top-0 z-[1100] border-b border-border bg-card/90 backdrop-blur">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5 md:px-6">
        <a href={hrefFor("mapa")} className="flex items-center gap-3 rounded-md">
          <Logo />
          <span className="leading-tight">
            <span className="block text-base font-semibold">LifeMap</span>
            <span className="hidden text-xs text-muted-foreground md:block">Reputación, ubicación y supervivencia de negocios</span>
          </span>
        </a>

        <nav aria-label="Principal" className="flex gap-1">
          {ROUTES.map((name) => (
            <a
              key={name}
              href={hrefFor(name)}
              aria-current={route === name ? "page" : undefined}
              className={cn(
                "inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium transition-colors duration-150 pointer-coarse:min-h-11",
                route === name ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {NAV_LABEL[name]}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <HealthPill />
          <Button variant="outline" size="icon" onClick={onToggleTheme} aria-label={theme === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro"} title={theme === "dark" ? "Tema claro" : "Tema oscuro"}>
            {theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
          </Button>
        </div>
      </div>
    </header>
  );
}
