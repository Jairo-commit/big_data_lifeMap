// Curvas de Kaplan-Meier de los grupos de SupervivenciaGrupos: una fila por instante con cierres.
// Una mediana vacía (null) en SupervivenciaGrupos significa que la curva nunca baja de 0,5: no existe mediana.
// URL: /survival/Restaurants
// QUERY: by=category&format=csv
// COLUMNS: group,kind,t,t_years,n_risk,n_events,n_censored,survival,ci_low,ci_high
let
    // La curva de un grupo, pedida a la API (el nombre puede llevar espacios o &, por eso se codifica)
    CurvaDe = (nombre as text) as table =>
        let
            Fuente = Csv.Document(
                Web.Contents(ApiUrl, [RelativePath = "survival/" & Uri.EscapeDataString(nombre), Query = [by = "category", format = "csv"]]),
                [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
            ),
            Encabezados = Table.PromoteHeaders(Fuente, [PromoteAllScalars = true]),
            SinVacios = Table.ReplaceValue(Encabezados, "", null, Replacer.ReplaceValue, Table.ColumnNames(Encabezados)),
            Tipos = Table.TransformColumnTypes(
                SinVacios,
                {
                    {"group", type text},
                    {"kind", type text},
                    {"t", Int64.Type},
                    {"t_years", type number},
                    {"n_risk", Int64.Type},
                    {"n_events", Int64.Type},
                    {"n_censored", Int64.Type},
                    {"survival", type number},
                    {"ci_low", type number},
                    {"ci_high", type number}
                },
                "en-US"
            )
        in
            Tipos,
    Nombres = Table.SelectColumns(SupervivenciaGrupos, {"group"}),
    ConCurva = Table.AddColumn(Nombres, "curva", each CurvaDe([group])),
    Filas = Table.Combine(ConCurva[curva])
in
    Filas
