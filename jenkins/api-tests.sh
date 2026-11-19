#!/usr/bin/env bash
# Basic tests against a running API, run by the Jenkinsfile on the staging stack before deploying.
# Each check calls one endpoint with curl and checks the JSON response with jq. Every check runs,
# then the script exits with 1 if any failed, which fails the build and stops the deploy.
#
# The staging MongoDB starts empty (no ingestion or Spark job runs in the pipeline) and there is no
# trained sentiment model, so the checks verify the shape of each response and the validation of
# the parameters, not the data. /predict accepts a prediction or the 503 for a model not trained.
#
# Usage: jenkins/api-tests.sh http://api:5000
set -uo pipefail

API="${1:?usage: $0 <API base URL, e.g. http://api:5000>}"
failures=0

# check <description> <jq expression that must be true> <curl arguments...>
check() {
    local description="$1" expression="$2"
    shift 2
    local body=""
    if body=$(curl -fsS --max-time 30 "$@") && jq -e "$expression" <<<"$body" >/dev/null; then
        echo "PASS  $description"
    else
        echo "FAIL  $description"
        echo "      expected: $expression"
        echo "      response: ${body:0:500}"
        failures=$((failures + 1))
    fi
}

# check_status <description> <expected HTTP status> <curl arguments...>
check_status() {
    local description="$1" expected="$2"
    shift 2
    local status
    status=$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "$@")
    if [[ "$status" == "$expected" ]]; then
        echo "PASS  $description"
    else
        echo "FAIL  $description (expected HTTP $expected, got $status)"
        failures=$((failures + 1))
    fi
}

# check_body <description> <jq expression that must be true> <curl arguments...>
# Like check, but also for error responses (4xx/5xx): the expression sees the body as is.
check_body() {
    local description="$1" expression="$2"
    shift 2
    local body=""
    if body=$(curl -sS --max-time 60 "$@") && jq -e "$expression" <<<"$body" >/dev/null; then
        echo "PASS  $description"
    else
        echo "FAIL  $description"
        echo "      expected: $expression"
        echo "      response: ${body:0:500}"
        failures=$((failures + 1))
    fi
}

# check_text <description> <grep -E pattern the body must match on its first line> <curl arguments...>
# For endpoints that answer CSV (Power BI): the header line must be there, even without rows.
check_text() {
    local description="$1" pattern="$2"
    shift 2
    local first=""
    if first=$(curl -fsS --max-time 30 "$@" | head -n 1) && grep -Eq "$pattern" <<<"$first"; then
        echo "PASS  $description"
    else
        echo "FAIL  $description"
        echo "      expected first line to match: $pattern"
        echo "      got: ${first:0:300}"
        failures=$((failures + 1))
    fi
}

echo "Testing the API at $API"

POINT='lat=36.1699&lon=-115.1398'   # Las Vegas
SQUARE='{"type": "Polygon", "coordinates": [[[-115.2, 36.1], [-115.1, 36.1], [-115.1, 36.2], [-115.2, 36.2], [-115.2, 36.1]]]}'
OPEN_RING='{"type": "Polygon", "coordinates": [[[-115.2, 36.1], [-115.1, 36.1], [-115.1, 36.2], [-115.2, 36.2]]]}'
JSON=(-H 'Content-Type: application/json')

check "GET /health: the API is up and MongoDB answers" \
    '.status == "ok" and .services.mongodb == "healthy" and (.services.sentiment_model | type == "string")' \
    "$API/health"

# /businesses/near ($near)
check "GET /businesses/near: businesses around a point, with category filter" \
    '.radius_m == 2000 and .category == "Pizza" and (.businesses | type == "array")
     and .returned == (.businesses | length)' \
    "$API/businesses/near?$POINT&radius=2000&category=Pizza&limit=5"
check_status "GET /businesses/near without lat: rejected with 400" 400 \
    "$API/businesses/near?lon=-115.1398"
check_status "GET /businesses/near with radius over the maximum: rejected with 400" 400 \
    "$API/businesses/near?$POINT&radius=999999"

# /businesses/within ($geoWithin)
check "POST /businesses/within: businesses inside a GeoJSON polygon" \
    '.geometry.type == "Polygon" and (.total | type == "number") and (.businesses | type == "array")' \
    -X POST "${JSON[@]}" -d "$SQUARE" "$API/businesses/within?limit=10"
check_status "POST /businesses/within with an open ring: rejected with 400" 400 \
    -X POST "${JSON[@]}" -d "$OPEN_RING" "$API/businesses/within"
check_status "POST /businesses/within with a Point: rejected with 400" 400 \
    -X POST "${JSON[@]}" -d '{"type": "Point", "coordinates": [-115.1, 36.1]}' "$API/businesses/within"

# /zones/summary ($geoNear)
check "GET /zones/summary: closure rate and sentiment around a point" \
    '.radius_m == 1500 and (.n_businesses | type == "number")
     and (.closure | has("closure_rate") and has("meets_min_days"))
     and (.sentiment | has("sentiment_score") and has("mean_stars"))' \
    "$API/zones/summary?$POINT&radius=1500&min_days=365"
check_status "GET /zones/summary without lon: rejected with 400" 400 \
    "$API/zones/summary?lat=36.1699"

# /stats/closure
check "GET /stats/closure by category with a minimum of business-days" \
    '.by == "category" and .min_business_days == 365 and (.results | type == "array")' \
    "$API/stats/closure?by=category&min_days=365"
check "GET /stats/closure by geohash cell" \
    '.by == "cell" and (.results | type == "array")' \
    "$API/stats/closure?by=cell&include_below_min=true&limit=5"
check_status "GET /stats/closure by an unknown grouping: rejected with 400" 400 \
    "$API/stats/closure?by=city"

# /predict
check_body "POST /predict: a sentiment for the text, or 503 while the model is not trained" \
    '(.sentiment | IN("negativo", "neutral", "positivo")) or .error == "model_not_available"' \
    -X POST "${JSON[@]}" -d '{"text": "The food was great and the staff were friendly"}' "$API/predict"
check_status "POST /predict with empty text: rejected with 400" 400 \
    -X POST "${JSON[@]}" -d '{"text": ""}' "$API/predict"
check_status "POST /predict without a JSON body: rejected with 400" 400 \
    -X POST "$API/predict"

# /health: Kafka is not configured in staging and must not degrade the API
check "GET /health: Kafka is reported as not configured and does not degrade the API" \
    '.status == "ok" and .services.kafka == "not_configured"' \
    "$API/health"

# /live/hotspots
check "GET /live/hotspots: the latest window and an array of hotspots (empty in staging)" \
    '.latest == true and (.hotspots | type == "array") and .returned == (.hotspots | length)' \
    "$API/live/hotspots?$POINT&radius=2000"
check_text "GET /live/hotspots as CSV: the header is there even without rows" '^geohash,window_start' \
    "$API/live/hotspots?format=csv"
check_status "GET /live/hotspots with lat but no lon: rejected with 400" 400 \
    "$API/live/hotspots?lat=36.1699"
check_status "GET /live/hotspots with an invalid window: rejected with 400" 400 \
    "$API/live/hotspots?window=junio"

# /live/evolution
check "GET /live/evolution: an array of windows" '(.windows | type == "array")' \
    "$API/live/evolution?$POINT&radius=2000"
check_status "GET /live/evolution with an unknown format: rejected with 400" 400 \
    "$API/live/evolution?format=xml"

# /alerts (radius with GET, polygon with POST)
check "GET /alerts: active alerts around a point" \
    '.state == "active" and .radius_m == 3000 and (.alerts | type == "array")' \
    "$API/alerts?$POINT&radius=3000&min_probability=0.5"
check_text "GET /alerts as CSV: the header is there even without rows" '^business_id,city' \
    "$API/alerts?format=csv"
check_status "GET /alerts with an unknown state: rejected with 400" 400 \
    "$API/alerts?state=viejas"
check_status "GET /alerts with min_probability over 1: rejected with 400" 400 \
    "$API/alerts?min_probability=2"
check "POST /alerts: alerts inside a polygon" '(.alerts | type == "array") and .geometry.type == "Polygon"' \
    -X POST "${JSON[@]}" -d "$SQUARE" "$API/alerts"
check_status "POST /alerts with an open ring: rejected with 400" 400 \
    -X POST "${JSON[@]}" -d "$OPEN_RING" "$API/alerts"

# /survival
check "GET /survival: the groups that have a curve" '(.groups | type == "array")' \
    "$API/survival?by=category&meets_min=true"
check_body "GET /survival/<unknown>: 404 survival_not_found" '.error == "survival_not_found"' \
    "$API/survival/Categoria%20que%20no%20existe"
check_status "GET /survival with an unknown grouping: rejected with 400" 400 \
    "$API/survival?by=ciudad"

# /risk/near
check "GET /risk/near: businesses around a point with their risk" \
    '.radius_m == 1000 and (.businesses | type == "array")' \
    "$API/risk/near?$POINT"
check_status "GET /risk/near without lat: rejected with 400" 400 \
    "$API/risk/near?lon=-115.1398"

if ((failures > 0)); then
    echo "$failures API check(s) failed"
    exit 1
fi
echo "All API checks passed"
