// CI/CD pipeline, run by a Multibranch Pipeline job that discovers main and the pull requests
// (see jenkins/JENKINS.md). Python stages use uv; Docker stages use the host's Docker through its
// socket (jenkins/Dockerfile).
//
// - Pull request into main: Install → Lint → Test.
// - main (every merge or push to it): the same, then
//   Build images → Start services (staging) → API tests → Deploy.
//
// Stages run in order and the build stops at the first failure, so the deploy only happens when
// every test before it passed.
//
// The project is still being built, so each group of stages runs only when the files it needs
// exist (table in jenkins/JENKINS.md). Until then it shows as skipped and the build stays green.
// Adding the files is enough to switch a group on: nobody needs to edit this file for that.

import groovy.transform.Field

// Staging: a copy of the stack with no published ports (jenkins/docker-compose.staging.yml),
// so it can run next to the deployed stack
@Field String STAGING = 'lifemap-staging'
@Field String STAGING_COMPOSE = "docker compose -p ${STAGING} -f docker-compose.yml -f jenkins/docker-compose.staging.yml"
// Network the services share in docker-compose.yml (`lifemap-net`), as Compose names it for staging
@Field String STAGING_NETWORK = "${STAGING}_lifemap-net"
// Deployed stack: docker-compose.yml as it is, with its published ports
@Field String PRODUCTION_COMPOSE = 'docker compose -p lifemap'
// API as seen from the staging network (service name and container port in docker-compose.yml)
@Field String STAGING_API_URL = 'http://api:5000'

// CI needs a uv project: pyproject.toml (with uv.lock committed)
boolean ciEnabled() {
    return fileExists('pyproject.toml')
}

// CD needs all three, so the stack is never deployed without its API tests
boolean cdEnabled() {
    return fileExists('docker-compose.yml') &&
        fileExists('jenkins/docker-compose.staging.yml') &&
        fileExists('jenkins/api-tests.sh')
}

// Removes the staging containers. Volumes are kept, so the next build reuses the loaded MongoDB
def stopStaging() {
    sh """
        docker network disconnect ${STAGING_NETWORK} "\$(hostname)" 2>/dev/null || true
        ${STAGING_COMPOSE} down || true
    """
}

pipeline {
    agent any

    options {
        timeout(time: 2, unit: 'HOURS')
        disableConcurrentBuilds()
    }

    stages {
        stage('CI') {
            when {
                allOf {
                    anyOf {
                        branch 'main'
                        changeRequest target: 'main'
                    }
                    expression { ciEnabled() }
                }
            }
            stages {
                stage('Install') {
                    steps {
                        sh 'uv sync --locked'
                    }
                }
                stage('Lint') {
                    steps {
                        sh 'uv run ruff check .'
                    }
                }
                stage('Test') {
                    steps {
                        // pytest exits with 5 when it collects no tests: that is not a failure
                        // while the project has none yet
                        sh '''
                            set +e
                            uv run pytest --junitxml=reports/junit.xml
                            status=$?
                            set -e
                            if [ "$status" -eq 5 ]; then
                                echo "No tests found yet"
                                exit 0
                            fi
                            exit "$status"
                        '''
                    }
                }
            }
        }

        stage('CD') {
            when {
                allOf {
                    branch 'main'
                    expression { cdEnabled() }
                }
            }
            stages {
                stage('Build images') {
                    steps {
                        // One image at a time, to keep memory low on this PC. spark-master,
                        // spark-worker and spark-jobs share lifemap-spark, so it is built once
                        // through spark-master (its profile has to be on to build it). Add here
                        // any new service that has its own `build:`
                        sh 'docker compose --profile jobs build spark-master'
                        sh 'docker compose build api'
                    }
                }
                stage('Start services') {
                    steps {
                        // Starts only the services without a profile (mongodb and api): Spark and
                        // Dask are only for the batch jobs (see docker-compose.yml). Waits until
                        // they are healthy. Secrets go in withCredentials([...]) { } around this sh
                        sh "${STAGING_COMPOSE} up -d --wait"
                    }
                }
                stage('API tests') {
                    steps {
                        // Jenkins joins the staging network to call the API by its service name
                        sh """
                            docker network disconnect ${STAGING_NETWORK} "\$(hostname)" 2>/dev/null || true
                            docker network connect ${STAGING_NETWORK} "\$(hostname)"
                        """
                        sh "jenkins/api-tests.sh ${STAGING_API_URL}"
                    }
                }
                stage('Deploy') {
                    steps {
                        script {
                            stopStaging()
                        }
                        // Recreates only the containers whose image or configuration changed
                        sh "${PRODUCTION_COMPOSE} up -d --wait"
                        sh "${PRODUCTION_COMPOSE} ps"
                    }
                }
            }
        }
    }

    post {
        always {
            // Shows the test results (passed/failed per test) on the build page
            junit allowEmptyResults: true, testResults: 'reports/junit.xml'
        }
        unsuccessful {
            script {
                if (env.BRANCH_NAME == 'main' && cdEnabled()) {
                    // Last log lines of the staging stack, to see from the build page what failed
                    sh "${STAGING_COMPOSE} logs --no-color --tail 100 || true"
                }
            }
        }
        cleanup {
            script {
                if (env.BRANCH_NAME == 'main' && cdEnabled()) {
                    stopStaging()
                }
            }
        }
    }
}
