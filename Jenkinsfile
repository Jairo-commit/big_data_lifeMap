// CI/CD pipeline, run by a Multibranch Pipeline job that discovers main and the pull requests.
// GitHub starts the builds instantly through a webhook (ngrok forwards it to this PC's Jenkins);
// see jenkins/JENKINS.md. Python stages use uv; Docker stages use the host's Docker through its
// socket (jenkins/Dockerfile).
//
// - Pull request into main: Install → Lint → Test.
// - main (every merge or push to it): the same, then
//   Build images → Start services (staging) → API tests → Deploy.
//
// The project is still being built, so every group of stages switches itself on when the files
// it needs exist (table "What turns each stage on" in jenkins/JENKINS.md):
// - CI needs pyproject.toml.
// - CD needs docker-compose.yml, jenkins/docker-compose.staging.yml and jenkins/api-tests.sh,
//   all three, so nothing is ever deployed without its API tests.
// Until then those stages show as skipped and the build stays green.
//
// Stages run in order and the build stops at the first failure, so the deploy only happens when
// every test before it passed.

import groovy.transform.Field

// Staging: a copy of the stack with no published ports (jenkins/docker-compose.staging.yml)
@Field String STAGING = 'lifemap-staging'
@Field String STAGING_COMPOSE = "docker compose -p ${STAGING} -f docker-compose.yml -f jenkins/docker-compose.staging.yml"
// Deployed stack: docker-compose.yml as it is
@Field String PRODUCTION_COMPOSE = 'docker compose -p lifemap'

def hasCI() {
    return fileExists('pyproject.toml')
}

def hasCD() {
    return fileExists('docker-compose.yml') &&
        fileExists('jenkins/docker-compose.staging.yml') &&
        fileExists('jenkins/api-tests.sh')
}

// Removes the staging containers. Volumes are kept, so the next build reuses the loaded data
def stopStaging() {
    sh """
        docker network disconnect ${STAGING}_default "\$(hostname)" 2>/dev/null || true
        ${STAGING_COMPOSE} down
    """
}

pipeline {
    agent any

    options {
        timeout(time: 3, unit: 'HOURS')
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
                    expression { hasCI() }
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
                        // pytest exits with 5 when it finds no tests: accepted while there are none
                        sh '''
                            status=0
                            uv run pytest --junitxml=reports/junit.xml || status=$?
                            if [ "$status" -eq 5 ]; then
                                echo "No tests found yet"
                            elif [ "$status" -ne 0 ]; then
                                exit "$status"
                            fi
                        '''
                    }
                }
            }
        }

        stage('CD') {
            when {
                allOf {
                    branch 'main'
                    expression { hasCD() }
                }
            }
            stages {
                stage('Build images') {
                    steps {
                        // If several services share one image, build only one service per image
                        // (e.g. `docker compose build etl spark`): parallel builds of the same
                        // image collide
                        sh 'docker compose build'
                    }
                }
                stage('Start services') {
                    steps {
                        // Waits until every service with a healthcheck is healthy.
                        // Secrets (API tokens…) go in Jenkins credentials and are exposed only
                        // inside a withCredentials([...]) { } block around this sh step
                        sh "${STAGING_COMPOSE} up -d --wait"
                    }
                }
                stage('API tests') {
                    steps {
                        // Jenkins joins the staging network to call the API by its service name.
                        // The URL assumes a service called `api` listening on 5000: change it to
                        // the real one
                        sh """
                            docker network disconnect ${STAGING}_default "\$(hostname)" 2>/dev/null || true
                            docker network connect ${STAGING}_default "\$(hostname)"
                        """
                        sh 'jenkins/api-tests.sh http://api:5000'
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
                if (env.BRANCH_NAME == 'main' && hasCD()) {
                    // Last log lines of the staging stack, to see from the build page what failed
                    sh "${STAGING_COMPOSE} logs --no-color --tail 100 || true"
                }
            }
        }
        cleanup {
            script {
                if (env.BRANCH_NAME == 'main' && hasCD()) {
                    stopStaging()
                }
            }
        }
    }
}
