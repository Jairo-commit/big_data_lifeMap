# LifeMap · Frontend

Interfaz web de LifeMap (React + TypeScript + Vite + Tailwind CSS 4) con dos vistas:

- **Mapa** (`#/mapa`): ejecuta las consultas geoespaciales de MongoDB a través de la API y dibuja los
  negocios de cada consulta como puntos. Al pasar el cursor sobre un punto aparece la ficha del negocio.
  - *Cerca de un punto* (`$near`): haz clic en el mapa o escribe las coordenadas, y elige el radio.
  - *Dentro de un polígono* (`$geoWithin`): dibuja los vértices con clics, o usa «Usar el área visible».
  - *Resumen de zona* (`$geoNear` + `$lookup` + `$group`): sentimiento medio y tasa de cierre de un radio,
    junto con los negocios que lo componen.
  - Cada consulta muestra la **consulta de MongoDB equivalente**, una tabla ordenable con los resultados y
    la leyenda: punto relleno = negocio abierto, punto hueco = cerrado.
- **Modelos** (`#/modelos`): los clasificadores de sentimiento entrenados con Spark (Naive Bayes y regresión
  logística): distribución de clases, comparación, precision/recall/F1 por clase, matrices de confusión,
  cómo se entrenaron y una caja para clasificar un texto en vivo con `/predict`.

Las cifras salen de la API (`/businesses/*`, `/zones/summary`, `/models`, `/predict`, `/health`); no hay datos
escritos a mano en la interfaz.

## Desarrollo

Requiere Node 24 y [pnpm](https://pnpm.io). La API debe estar en marcha (por defecto en
`http://localhost:5000`; con otra dirección, `API_URL`). El servidor de desarrollo reenvía `/api` a la API,
así que no hace falta CORS.

```bash
cd frontend
pnpm install
pnpm dev                                  # http://localhost:5173
API_URL=http://localhost:5001 pnpm dev    # contra otra API
```

La vista *Modelos* usa `GET /models`, que se añadió a la API junto con este frontend: hace falta una API
con ese endpoint y modelos entrenados (`sentiment_model.py`).

| Comando | Qué hace |
|---|---|
| `pnpm dev` | Servidor de desarrollo con recarga |
| `pnpm build` | Revisa los tipos y genera `dist/` |
| `pnpm typecheck` | Solo revisa los tipos |
| `pnpm test` | Pruebas unitarias (Vitest) de formato, geometría y métricas |

## Con Docker

El servicio `frontend` del `docker-compose.yml` no arranca con un `up` normal; se activa con su perfil:

```bash
docker compose --profile frontend up -d frontend    # http://localhost:3000
```

La imagen compila con pnpm y sirve con nginx, que reenvía `/api` a la API (`API_UPSTREAM`, por defecto
`http://api:5000`; en Compose se cambia con `FRONTEND_API_UPSTREAM`). El proxy espera hasta 300 s, porque el
resumen de zona puede tardar decenas de segundos.

## Estructura

```
src/
  lib/            cliente de la API (api.ts), formato, geometría, métricas, tema y rutas (+ pruebas)
  components/     Header, ErrorBoundary y ui/ (Button, Card, Badge, formularios, control segmentado)
  features/map/   MapView, MapCanvas (Leaflet), QueryPanel, ResultsTable, ZoneSummary, mongo.ts
  features/models/ ModelsView y sus tarjetas (distribución, comparación, gráfico, matrices, prueba)
  styles/tokens.css   tokens de diseño
```

## Diseño

- **Tokens en tres capas** (`styles/tokens.css`): primitivos (paleta, radios, movimiento) → semánticos
  (fondo, texto, sentimiento, estado) → de componente (tarjeta, botón, tooltip, mapa). Los componentes solo
  leen las dos últimas, así que el tema claro y el oscuro son solo una redefinición de la capa semántica.
  Sigue el tema del sistema y se puede alternar desde la cabecera.
- **Color con significado, nunca solo**: los colores de sentimiento y de estado vienen de la paleta Okabe-Ito
  (apta para daltonismo) y siempre van con etiqueta, y los puntos cerrados se distinguen por ser huecos. En el
  gráfico, el segundo modelo lleva un rayado además de su color.
- **Accesibilidad**: se auditó con axe-core (reglas WCAG 2 A/AA y buenas prácticas) en las dos vistas y los
  dos temas, sin violaciones. Hay enlace para saltar al contenido, foco visible, navegación por teclado,
  etiquetas en todos los campos, errores junto al campo, `aria-sort` en la tabla, tabla alternativa junto a cada
  gráfico y respeto a `prefers-reduced-motion`. Como los puntos del mapa no se alcanzan con el teclado, cada
  consulta ofrece la misma información en la tabla de resultados.

## Límites conocidos

- `/zones/summary` suma las reseñas de cada negocio con un `$lookup`: tarda unos 7 s con 500 m y unos 30 s con
  2 km, y más con radios mayores. La interfaz limita ese modo a radios de hasta 2 km, muestra el avance y
  permite cancelar. Precalcular los totales por negocio en la API lo haría casi instantáneo.
- La API devuelve como máximo 200 negocios en `$near` y 1000 en `$geoWithin`; la interfaz avisa cuando se
  alcanza el límite.
- El mapa base usa las teselas públicas de OpenStreetMap, pensadas para un uso moderado. Para tráfico real,
  conviene un proveedor propio.
