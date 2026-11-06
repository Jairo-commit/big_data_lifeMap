# Checking the API endpoints locally

A step-by-step guide to start LifeMap on your PC and call every endpoint with `curl`.
`jq` is optional: it only pretty-prints the JSON (`sudo apt install jq`). Without it, drop the
`| jq` at the end of each command.

## 1. Start the API

**If Jenkins already deployed LifeMap on this PC**, the API is running: check it with
`docker compose -p lifemap ps` and skip to step 2. Add `-p lifemap` to every `docker compose`
command in this guide (`docker compose -p lifemap exec mongodb ...`), so they use the deployed
stack and its data. Do not run the `up` below then: both stacks use the same ports (5000, 27017)
and the second one fails with `port is already allocated`.

Otherwise, from the repository root:

```bash
docker compose build api
docker compose up -d --wait mongodb api
```

`--wait` returns when both are healthy. The API is at **http://localhost:5000**.

## 2. Make sure there is data

Each endpoint reads something different from MongoDB:

| Endpoint | Needs | Comes from |
|---|---|---|
| `/health` | nothing | always works |
| `/businesses/near`, `/businesses/within`, `/zones/summary` | `businesses` and `reviews` | ingestion (points 2 and 3) |
| `/stats/closure` | `closure_by_category`, `closure_by_geohash` | `closure_rates.py` (point 5) |
| `/predict` | the `sentiment_best` model | `sentiment_model.py` (point 4) |

Check what is loaded:

```bash
docker compose exec mongodb mongosh --quiet lifemap_db --eval '
  printjson({
    businesses: db.businesses.countDocuments({}),
    reviews: db.reviews.countDocuments({}),
    closure_by_category: db.closure_by_category.countDocuments({}),
    closure_by_geohash: db.closure_by_geohash.countDocuments({})
  })'
```

If the closure collections or the model are missing, run the Spark jobs (README), then stop Spark:

```bash
docker compose --profile jobs run --rm spark-jobs spark-submit /app/sentiment_model.py
docker compose --profile jobs run --rm spark-jobs spark-submit /app/closure_rates.py
docker compose stop spark-master spark-worker
```

## 3. Pick a point that has businesses

The geospatial endpoints need a point near your data. Take the coordinates of any business:

```bash
docker compose exec mongodb mongosh --quiet lifemap_db --eval '
  const b = db.businesses.findOne({location: {$exists: true}}, {name: 1, city: 1, location: 1});
  if (b) print(b.name, "-", b.city, "- lon lat:", b.location.coordinates.join(" "));
  else print("No businesses with a location yet: run the ingestion (points 2 and 3) first")'
```

Save them in variables so you can paste the commands below as they are (example values for
Philadelphia; use the ones you got):

```bash
API=http://localhost:5000
LAT=39.9526
LON=-75.1652
```

## 4. Call each endpoint

### `GET /health`: is the API up?

```bash
curl -s $API/health | jq
```

Expected: `"status": "ok"`, `"mongodb": "healthy"`, and `sentiment_model` is `loaded`,
`not_loaded` (trained, loads on the first `/predict`) or `not_trained`.

### `GET /businesses/near`: businesses around a point (`$near`)

```bash
# 20 closest businesses within 1 km (default radius and limit)
curl -s "$API/businesses/near?lat=$LAT&lon=$LON" | jq

# 2 km, only pizza places, 5 results
curl -s "$API/businesses/near?lat=$LAT&lon=$LON&radius=2000&category=Pizza&limit=5" | jq
```

| Parameter | Required | Default | |
|---|---|---|---|
| `lat`, `lon` | yes | | the point |
| `radius` | no | `1000` | meters, up to 50000 |
| `category` | no | | one whole Yelp category, case-insensitive (`Pizza` does not match `Pizza Delivery`) |
| `limit` | no | `20` | up to 200 |

Expected: `businesses` sorted from closest to farthest, each with its `distance_m`.

### `POST /businesses/within`: businesses inside a polygon (`$geoWithin`)

The body is a GeoJSON `Polygon`, `MultiPolygon` or a `Feature` with one of them. Coordinates are
`[lon, lat]` and the ring must be closed (first point = last point). This square is about 2 km
around the point:

```bash
POLYGON=$(awk -v lat="$LAT" -v lon="$LON" 'BEGIN {
  d = 0.01
  printf "{\"type\": \"Polygon\", \"coordinates\": [[[%f,%f],[%f,%f],[%f,%f],[%f,%f],[%f,%f]]]}",
    lon-d, lat-d,  lon+d, lat-d,  lon+d, lat+d,  lon-d, lat+d,  lon-d, lat-d }')
echo "$POLYGON"

curl -s -X POST "$API/businesses/within?limit=10" \
  -H 'Content-Type: application/json' -d "$POLYGON" | jq
```

Query parameters: `category` and `limit` (default `100`, up to 1000).
Expected: `total` (all businesses inside) and `businesses` (up to `limit` of them).

### `GET /zones/summary`: sentiment and closure rate around a point (`$geoNear`)

```bash
curl -s "$API/zones/summary?lat=$LAT&lon=$LON&radius=1500" | jq

# Only restaurants, with a minimum of 1 year of business-days
curl -s "$API/zones/summary?lat=$LAT&lon=$LON&radius=1500&category=Restaurants&min_days=365" | jq
```

Parameters: `lat`, `lon` (required), `radius` (meters, default `1000`), `category`, `min_days`
(default `3650`).

Expected:
- `n_businesses`: businesses in the circle.
- `closure.closure_rate`: annualized closure rate (closures / (business-days / 365) × 100), and
  `meets_min_days`: whether the zone has at least `min_days` business-days (below that, the rate
  is noise).
- `sentiment.sentiment_score`: from -1 (all negative) to 1 (all positive), with the same rule as
  the model's labels (1-2 stars negative, 3 neutral, 4-5 positive), plus `mean_stars` and the
  percentage of each class.

### `GET /stats/closure`: closure rates by category or by cell

```bash
# 10 categories with the highest closure rate, with at least 10 years of business-days
curl -s "$API/stats/closure?by=category&min_days=3650&limit=10" | jq

# Geohash cells, lowest rate first, including the ones below the minimum
curl -s "$API/stats/closure?by=cell&order=asc&include_below_min=true&limit=5" | jq
```

| Parameter | Default | |
|---|---|---|
| `by` | `category` | `category` or `cell` (geohash cell, with its polygon in `geometry`) |
| `min_days` | `3650` | minimum business-days of the group |
| `include_below_min` | `false` | also return the groups below the minimum, with `meets_min_days: false` |
| `order` | `desc` | `desc` or `asc` by `closure_rate` |
| `limit` | `20` | up to 1000 |

### `POST /predict`: sentiment of a new text

```bash
curl -s -X POST $API/predict -H 'Content-Type: application/json' \
  -d '{"text": "The food was amazing and the staff were really friendly"}' | jq

curl -s -X POST $API/predict -H 'Content-Type: application/json' \
  -d '{"text": "Cold food, rude waiter, never coming back"}' | jq
```

Expected: `sentiment` (`negativo`, `neutral` or `positivo`) and the probability of each class.
The first call after starting the API takes a few seconds: it loads the model.

## 5. Errors you should see

Bad input answers `400` with a message in `error`:

```bash
curl -s "$API/businesses/near?lon=$LON" | jq                       # missing lat
curl -s "$API/stats/closure?by=city" | jq                          # unknown grouping
curl -s -X POST $API/predict -H 'Content-Type: application/json' -d '{"text": ""}' | jq
```

## Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| `curl: (7) Failed to connect` | The API is not running | `docker compose ps`, `docker compose logs api` |
| Empty `businesses`, `n_businesses: 0` | No data near the point, or no data at all | Step 2 and step 3 |
| `/stats/closure` returns `"results": []` | Point 5 has not run, or no group reaches `min_days` | Run `closure_rates.py`, or add `include_below_min=true` |
| `/predict` answers `503` `model_not_available` | Point 4 has not run | Run `sentiment_model.py`; no API restart needed |

## 6. Stop it

```bash
docker compose stop api mongodb      # stops them; the data stays in the volumes
```
