// Evolución del % de reseñas negativas por ventana de 30 días, en cada una de las ciudades con más negocios (radio de 20 km).
// URL: /live/evolution
// QUERY: lat=39.9526&lon=-75.1652&radius=20000&format=csv
// COLUMNS: window_start,window_end,n_cells,n_reviews,n_negative,pct_negative,pct_negative_stars,n_hotspots
let
    Zonas = #table(
        type table [zona = text, lat = number, lon = number],
        {
            {"Philadelphia, PA", 39.9526, -75.1652},
            {"Tucson, AZ", 32.2226, -110.9747},
            {"Tampa, FL", 27.9506, -82.4572},
            {"Indianapolis, IN", 39.7684, -86.1581},
            {"Nashville, TN", 36.1627, -86.7816},
            {"New Orleans, LA", 29.9511, -90.0715},
            {"Reno, NV", 39.5296, -119.8138},
            {"Edmonton, AB", 53.5461, -113.4938},
            {"Saint Louis, MO", 38.627, -90.1994}
        }
    ),
    EvolucionDe = (lat as number, lon as number) as table =>
        let
            Fuente = Csv.Document(
                Web.Contents(
                    ApiUrl,
                    [
                        RelativePath = "live/evolution",
                        Query = [lat = Number.ToText(lat, "0.0000", "en-US"), lon = Number.ToText(lon, "0.0000", "en-US"), radius = "20000", format = "csv"]
                    ]
                ),
                [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
            ),
            Encabezados = Table.PromoteHeaders(Fuente, [PromoteAllScalars = true]),
            SinVacios = Table.ReplaceValue(Encabezados, "", null, Replacer.ReplaceValue, Table.ColumnNames(Encabezados)),
            Tipos = Table.TransformColumnTypes(
                SinVacios,
                {
                    {"window_start", type datetime},
                    {"window_end", type datetime},
                    {"n_cells", Int64.Type},
                    {"n_reviews", Int64.Type},
                    {"n_negative", Int64.Type},
                    {"pct_negative", type number},
                    {"pct_negative_stars", type number},
                    {"n_hotspots", Int64.Type}
                },
                "en-US"
            )
        in
            Tipos,
    ConSerie = Table.AddColumn(Zonas, "serie", each EvolucionDe([lat], [lon])),
    Expandida = Table.ExpandTableColumn(
        ConSerie, "serie", {"window_start", "window_end", "n_cells", "n_reviews", "n_negative", "pct_negative", "pct_negative_stars", "n_hotspots"}
    ),
    // Al expandir se pierden los tipos de las columnas: sin este paso Power BI las trata como texto (las cuenta en vez de promediarlas)
    Tipos = Table.TransformColumnTypes(
        Expandida,
        {
            {"zona", type text},
            {"lat", type number},
            {"lon", type number},
            {"window_start", type datetime},
            {"window_end", type datetime},
            {"n_cells", Int64.Type},
            {"n_reviews", Int64.Type},
            {"n_negative", Int64.Type},
            {"pct_negative", type number},
            {"pct_negative_stars", type number},
            {"n_hotspots", Int64.Type}
        },
        "en-US"
    )
in
    Tipos
