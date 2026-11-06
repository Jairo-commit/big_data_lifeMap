#!/usr/bin/env bash
# Basic tests against a running API, run by the Jenkinsfile on the staging stack before deploying.
# Each check calls one endpoint with curl and checks the JSON response with jq. Every check runs,
# then the script exits with 1 if any failed, which fails the build and stops the deploy.
#
# The staging MongoDB starts empty (no ingestion runs in the pipeline), so the checks do not
# depend on loaded data. /businesses/near is not checked: $near needs the 2dsphere index that
# the ingestion creates.
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

echo "Testing the API at $API"

check "GET /health: the API is up and MongoDB answers" \
    '.status == "ok" and .services.mongodb == "healthy"' \
    "$API/health"

check "GET /stats/closure: closure rates by category, as a list" \
    'type == "array"' \
    "$API/stats/closure?min_days=365"

check "POST /predict: returns a sentiment for the text" \
    '.text == "The food was great and the staff were friendly"
     and (.predicted_sentiment | type == "string" and length > 0)' \
    -X POST -H 'Content-Type: application/json' \
    -d '{"text": "The food was great and the staff were friendly"}' \
    "$API/predict"

check_status "POST /predict with empty text: rejected with 400" 400 \
    -X POST -H 'Content-Type: application/json' -d '{"text": ""}' \
    "$API/predict"

if ((failures > 0)); then
    echo "$failures API check(s) failed"
    exit 1
fi
echo "All API checks passed"
