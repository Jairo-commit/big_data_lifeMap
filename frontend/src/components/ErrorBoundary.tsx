import { TriangleAlert } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface State {
  error: Error | null;
}

/** Si una vista falla al pintar, se muestra el error en lugar de dejar la página en blanco. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Error en la vista", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/40 bg-destructive-surface px-4 py-3 text-sm text-destructive">
        <TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
        <p className="flex-1">Algo falló al mostrar esta vista: {this.state.error.message}</p>
        <Button size="sm" variant="outline" onClick={() => this.setState({ error: null })}>
          Reintentar
        </Button>
      </div>
    );
  }
}
