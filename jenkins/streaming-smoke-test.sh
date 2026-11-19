#!/usr/bin/env bash
# Smoke test of the streaming flow, run by the Jenkinsfile (stage "Streaming tests") on the deployed stack.
#
# It publishes 100 synthetic reviews to a separate Kafka topic (reviews-smoke), runs the same streaming inference job as production
# (Kafka -> Spark Structured Streaming + the saved model -> MongoDB) and checks that all 100 appear **classified** in MongoDB
# (spark_batch/verify_smoke.py). It uses its own topic, checkpoint and collection, so it never touches the real reviews, and it
# removes all of them at the end. Exits with 1 if anything fails, which fails the build and stops the deploy.
#
# Usage: jenkins/streaming-smoke-test.sh      (PROD = the docker compose command of the deployed stack, set by the Jenkinsfile)
set -euo pipefail

COMPOSE="${PROD:-docker compose}"
RUN_ID="$(tr -c 'A-Za-z0-9' '-' <<<"${BUILD_TAG:-local}-$(date +%s)" | sed 's/-*$//')"
TOPIC="reviews-smoke"
COLLECTION="review_predictions_smoke"
CHECKPOINT="/app/checkpoints/smoke"
TIMEOUT="${SMOKE_TIMEOUT:-120}"   # seconds the streaming job runs: Spark starts, loads the model and processes the 100 messages

publisher() { $COMPOSE --profile streaming run --rm --entrypoint python producer smoke_publish.py --run-id "$RUN_ID" --topic "$TOPIC" "$@"; }
in_spark() { $COMPOSE --profile jobs run --rm spark-jobs "$@"; }

cleanup() {
    echo "== Cleaning up the topic, the collection and the checkpoint of the smoke test"
    publisher --cleanup || true
    in_spark python3 /app/verify_smoke.py --run-id "$RUN_ID" --collection "$COLLECTION" --cleanup || true
    in_spark python3 -c "import shutil; shutil.rmtree('$CHECKPOINT', ignore_errors=True)" || true
}
trap cleanup EXIT

echo "== 1/3 Publishing 100 reviews to '$TOPIC' (run $RUN_ID)"
publisher

echo "== 2/3 Classifying them with the streaming inference job (${TIMEOUT} s)"
in_spark spark-submit /app/streaming_inference.py --topic "$TOPIC" --output-collection "$COLLECTION" \
    --checkpoint "$CHECKPOINT" --reset --timeout "$TIMEOUT"

echo "== 3/3 Checking that the 100 reviews are classified in MongoDB"
in_spark python3 /app/verify_smoke.py --run-id "$RUN_ID" --collection "$COLLECTION"
