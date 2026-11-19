// Tabla de alertas activas: negocios cuya probabilidad de cierre supera el umbral, de la más alta a la más baja.
// URL: /alerts
// QUERY: state=active&limit=2000&format=csv
// COLUMNS: business_id,city,primary_category,probability,threshold,active,alert_date,first_alert_date,risk_at_cutoff,n_updates,lat,lon,mean_sentiment,neg_trend_6m,stars_mean,n_reviews,age_days,competitors_500m
let
    Fuente = Csv.Document(
        Web.Contents(ApiUrl, [RelativePath = "alerts", Query = [state = "active", limit = "2000", format = "csv"]]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Encabezados = Table.PromoteHeaders(Fuente, [PromoteAllScalars = true]),
    SinVacios = Table.ReplaceValue(Encabezados, "", null, Replacer.ReplaceValue, Table.ColumnNames(Encabezados)),
    Tipos = Table.TransformColumnTypes(
        SinVacios,
        {
            {"business_id", type text},
            {"city", type text},
            {"primary_category", type text},
            {"probability", type number},
            {"threshold", type number},
            {"active", type logical},
            {"alert_date", type datetime},
            {"first_alert_date", type datetime},
            {"cleared_date", type datetime},
            {"risk_at_cutoff", type number},
            {"n_updates", Int64.Type},
            {"lat", type number},
            {"lon", type number},
            {"mean_sentiment", type number},
            {"neg_trend_6m", type number},
            {"stars_mean", type number},
            {"n_reviews", Int64.Type},
            {"age_days", Int64.Type},
            {"competitors_500m", Int64.Type}
        },
        "en-US"
    )
in
    Tipos
