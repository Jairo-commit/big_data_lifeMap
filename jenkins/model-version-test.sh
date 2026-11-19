#!/usr/bin/env bash
# Checks that the model loaded is the versioned one, run by the Jenkinsfile (stage "Streaming tests") on the deployed stack.
#
# spark_batch/register_models.py stores the version (uid@timestamp) and the SHA-256 of each saved model in MongoDB (model_registry).
# spark_batch/verify_model_version.py then checks that the model on disk (what the streaming jobs load) is the registered one, and that the
# model the API answered with (/predict) and reports (/health) is the registered one too. Exits with 1 if not, which fails the build.
#
# Usage: jenkins/model-version-test.sh      (PROD = the docker compose command of the deployed stack, set by the Jenkinsfile)
set -euo pipefail

COMPOSE="${PROD:-docker compose}"
API="${API_URL:-http://api:5000}"

$COMPOSE --profile jobs run --rm spark-jobs python3 /app/verify_model_version.py --api "$API"
