# Jenkins with the tools the pipeline (Jenkinsfile) uses:
# - uv: installs Python 3.13 and the locked dependencies (uv.lock) to lint and test the code.
# - Docker CLI with the compose and buildx plugins: builds the images and starts the stack.
#   There is no Docker daemon inside: the CLI talks to the host's Docker through its socket,
#   which is mounted when the container starts (see jenkins/JENKINS.md).
# - jq: checks the JSON responses in the API tests (jenkins/api-tests.sh). curl is already
#   in the Jenkins image.
FROM jenkins/jenkins:lts-jdk21

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/
COPY --from=docker:cli /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

USER jenkins
