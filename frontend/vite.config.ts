import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vitest/config";

// En desarrollo, /api se reenvía a la API de Flask (sin CORS). En producción lo hace nginx.
const API_URL = process.env.API_URL ?? "http://localhost:5000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  server: {
    port: 5173,
    proxy: { "/api": { target: API_URL, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
