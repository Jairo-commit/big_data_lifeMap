# Dashboard de Power BI

El reporte consume la API de LifeMap: cada visualización sale de una consulta de Power Query (M) de `queries/` que llama a un
endpoint con `?format=csv`. Power BI Desktop es una aplicación de Windows y el archivo `.pbix` no se genera por código, así que el repositorio
trae las consultas, esta guía paso a paso y un verificador (`check_queries.py`) que comprueba que la API devuelve lo que cada consulta necesita.

| Visualización | Consulta | Endpoint | Se llena con |
|---|---|---|---|
| 1. Mapa de hotspots | `Hotspots.pq` | `/live/hotspots` | `streaming_windows.py` |
| 2. Tabla de alertas activas | `Alertas.pq` | `/alerts` | `streaming_alerts.py` |
| 3. Curvas de supervivencia | `SupervivenciaGrupos.pq`, `SupervivenciaCurvas.pq` | `/survival`, `/survival/<categoría>` | `survival_km.py` |
| 4. Evolución del % negativo | `Evolucion.pq` | `/live/evolution` | `streaming_windows.py` |

## 0. Antes de abrir Power BI

La API debe estar en marcha con datos. En WSL:

```bash
docker compose up -d --build mongodb kafka kafka-init api   # la API queda en http://localhost:5000
python3 powerbi/check_queries.py --api http://localhost:5000 --require-rows
```

Debe decir `TODO OK` (cada consulta devuelve las columnas que usa el reporte). Si una tabla llega vacía hay que ejecutar el job de la tabla anterior
(`streaming_windows.py` con el productor para hotspots y evolución, `streaming_alerts.py` para las alertas, `survival_km.py` para las curvas).
Power BI Desktop (Windows) llega a `http://localhost:5000` porque WSL2 reenvía los puertos publicados; si no, usa la IP de WSL (`hostname -I`).

## 1. Cargar las consultas

1. **Inicio → Transformar datos → Nuevo origen → Consulta en blanco**, y en **Administrar parámetros → Nuevo parámetro**, crea:
   nombre `ApiUrl`, tipo *Texto*, valor actual `http://localhost:5000` (sin barra final).
2. Para cada archivo de `queries/` crea una **consulta en blanco**, abre el **Editor avanzado**, pega el contenido del `.pq` y ponle **exactamente** el nombre del
   archivo (`Hotspots`, `Alertas`, `SupervivenciaGrupos`, `SupervivenciaCurvas`, `Evolucion`): `SupervivenciaCurvas` depende de `SupervivenciaGrupos` por su nombre.
3. Si pide credenciales, elige **Anónimo** para `http://localhost:5000`. Si avisa de niveles de privacidad, en **Archivo → Opciones → Seguridad** elige
   *Ignorar los niveles de privacidad* (el origen es tu propia API).
4. **Cerrar y aplicar**.

## 2. Las cuatro visualizaciones

1. **Mapa de hotspots** (visual *Mapa*, burbujas): *Latitud* = `lat`, *Longitud* = `lon`, *Tamaño* = `delta_pp` (cuántos puntos subió el % negativo),
   *Color* = `pct_negative`, *Información sobre herramientas* = `geohash`, `n_reviews`, `prev_pct_negative`. Un segmentador de `window_start` permite ver otras ventanas
   de la misma tabla. (Si el visual no aparece: **Archivo → Opciones → Seguridad → Usar visuales de Mapa y Mapa de relleno**.)
2. **Tabla de alertas activas** (visual *Tabla*): `city`, `primary_category`, `probability`, `alert_date`, `risk_at_cutoff`, `n_updates`. Ordena por `probability` descendente y
   aplica *Formato condicional → Barras de datos* a `probability`. Una tarjeta con `Alertas activas = COUNTROWS(Alertas)` acompaña la tabla.
3. **Curvas de supervivencia** (visual *Gráfico de líneas*): *Eje X* = `t_years` (años de vida), *Valores* = `survival`, *Leyenda* = `group`, de la consulta `SupervivenciaCurvas`.
   Añade un segmentador de `group` para comparar categorías y `ci_low` / `ci_high` como líneas punteadas si quieres el intervalo de confianza del 95 %. `n_risk` va en el
   tooltip (el número en riesgo). La mediana de vida está en `SupervivenciaGrupos[median_years]`; **una mediana vacía significa que la curva nunca baja de 0,5**, no un dato faltante.
4. **Evolución del % negativo** (visual *Gráfico de líneas*): *Eje X* = `window_start`, *Valores* = `pct_negative`, *Leyenda* = `zona`, de la consulta `Evolucion`. Un
   segundo gráfico de columnas con `n_hotspots` muestra cuántas celdas se disparan en cada ventana.

## 3. Actualizar durante la demo

Con el origen *Web* en modo **Importar**, Power BI Desktop no se actualiza solo: pulsa **Inicio → Actualizar** (o configura *Actualización automática de página*, que
solo existe para DirectQuery y no aplica aquí). Para la demo en vivo: levanta `streaming_windows.py` y `streaming_alerts.py`, arranca el productor
(`docker compose --profile streaming run --rm producer --speed-seconds 3`) y pulsa *Actualizar* cada vez que se cierre una ventana: el mapa, la tabla y la evolución cambian.

## 4. Si algo no cuadra

- `python3 powerbi/check_queries.py` dice qué consulta falla y por qué (HTTP, columnas que faltan o tabla vacía).
- *Error de DataFormat con un número vacío*: las consultas ya reemplazan los vacíos por `null`; si cambias una consulta, conserva el paso `SinVacios`.
- Una consulta de hotspots vacía antes de la primera ventana cerrada es normal: la API devuelve la tabla con su encabezado y sin filas.
