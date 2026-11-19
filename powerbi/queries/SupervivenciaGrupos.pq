// Grupos con curva de supervivencia (categorías con negocios y cierres suficientes): sirve de segmentador y resumen.
// URL: /survival
// QUERY: by=category&meets_min=true&limit=30&format=csv
// COLUMNS: group,kind,n_businesses,n_events,n_censored,n_late_entry,median_days,median_years,meets_min,survival_1y,survival_3y,survival_5y,survival_10y
let
    Fuente = Csv.Document(
        Web.Contents(ApiUrl, [RelativePath = "survival", Query = [by = "category", meets_min = "true", limit = "30", format = "csv"]]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Encabezados = Table.PromoteHeaders(Fuente, [PromoteAllScalars = true]),
    SinVacios = Table.ReplaceValue(Encabezados, "", null, Replacer.ReplaceValue, Table.ColumnNames(Encabezados)),
    Tipos = Table.TransformColumnTypes(
        SinVacios,
        {
            {"group", type text},
            {"kind", type text},
            {"n_businesses", Int64.Type},
            {"n_events", Int64.Type},
            {"n_censored", Int64.Type},
            {"n_late_entry", Int64.Type},
            {"median_days", Int64.Type},
            {"median_years", type number},
            {"meets_min", type logical},
            {"survival_1y", type number},
            {"survival_3y", type number},
            {"survival_5y", type number},
            {"survival_10y", type number}
        },
        "en-US"
    )
in
    Tipos
