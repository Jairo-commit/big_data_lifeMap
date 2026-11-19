// Mapa de hotspots: celdas de geohash de la ventana de 30 días más reciente cuyo % de reseñas negativas se disparó.
// URL: /live/hotspots
// QUERY: window=latest&limit=2000&format=csv
// COLUMNS: geohash,window_start,window_end,n_reviews,n_negative,pct_negative,prev_pct_negative,delta_pp,threshold_pp,lat,lon
let
    Fuente = Csv.Document(
        Web.Contents(ApiUrl, [RelativePath = "live/hotspots", Query = [window = "latest", limit = "2000", format = "csv"]]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Encabezados = Table.PromoteHeaders(Fuente, [PromoteAllScalars = true]),
    SinVacios = Table.ReplaceValue(Encabezados, "", null, Replacer.ReplaceValue, Table.ColumnNames(Encabezados)),
    Tipos = Table.TransformColumnTypes(
        SinVacios,
        {
            {"geohash", type text},
            {"window_start", type datetime},
            {"window_end", type datetime},
            {"n_reviews", Int64.Type},
            {"n_negative", Int64.Type},
            {"pct_negative", type number},
            {"prev_pct_negative", type number},
            {"delta_pp", type number},
            {"threshold_pp", type number},
            {"lat", type number},
            {"lon", type number}
        },
        "en-US"
    )
in
    Tipos
