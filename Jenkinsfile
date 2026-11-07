// LifeMap CI/CD (Multibranch Pipeline, see jenkins/JENKINS.md).
// - CI, on pull requests into main and on main: Install → Lint → Test.
// - CD, on main only: Build images → API tests (staging) → Deploy → Ingest → Spark jobs.
// Steps run in order; if one fails the build stops and nothing after it runs.

pipeline {
    agent any

    options {
        timeout(time: 6, unit: 'HOURS')   // the Spark jobs on the whole dataset take long
        disableConcurrentBuilds()
    }

    environment {
        // Staging: a copy of the stack with no published ports, only for the API tests
        STAGING = 'docker compose -p lifemap-staging -f docker-compose.yml -f jenkins/docker-compose.staging.yml'
        // Deployed stack
        PROD = 'docker compose -p lifemap'
    }

    stages {
        stage('CI') {
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
                        sh 'uv run pytest --junitxml=reports/junit.xml'
                    }
                }
            }
        }

        stage('CD') {
            when { branch 'main' }
            stages {
                stage('Build images') {
                    steps {
                        // One image at a time: lifemap-spark (spark-master, spark-worker, spark-jobs) and the API
                        sh 'docker compose --profile jobs build spark-master'
                        sh 'docker compose build api'
                        sh 'docker compose --profile ingest build ingest'
                    }
                }
                stage('API tests') {
                    steps {
                        // Starts mongodb and api in staging, Jenkins joins its network and tests the API
                        sh '$STAGING up -d --wait'
                        sh 'docker network connect lifemap-staging_lifemap-net "$(hostname)"'
                        sh 'jenkins/api-tests.sh http://api:5000'
                        sh 'docker network disconnect lifemap-staging_lifemap-net "$(hostname)"'
                        sh '$STAGING down'
                    }
                }
                stage('Deploy') {
                    steps {
                        sh '$PROD up -d --wait'
                    }
                }
                stage('Ingest') {
                    steps {
                        // Validates the Yelp files in the yelp_data volume and downloads them from Kaggle
                        // only if missing (credential `kaggle`), then loads the full dataset into MongoDB
                        withCredentials([usernamePassword(credentialsId: 'kaggle',
                                usernameVariable: 'KAGGLE_USERNAME', passwordVariable: 'KAGGLE_KEY')]) {
                            sh '$PROD --profile ingest run --rm ingest'
                        }
                    }
                }
                stage('Spark jobs') {
                    steps {
                        // The README commands, one at a time, on the deployed stack
                        sh '$PROD up -d --wait spark-master spark-worker'
                        sh '$PROD --profile jobs run --rm spark-jobs spark-submit /app/sentiment_model.py'         // point 4
                        sh '$PROD --profile jobs run --rm spark-jobs spark-submit /app/closure_rates.py'           // point 5
                        sh '$PROD --profile jobs run --rm spark-jobs spark-submit /app/load_balancing.py --reps 3' // point 6
                        // Stops only Spark and Dask (`stop` without names would also stop mongodb and the API)
                        sh '$PROD stop spark-master spark-worker dask-scheduler dask-worker-1 dask-worker-2'
                    }
                }
            }
        }
    }

    post {
        always {
            // pytest results on the build page
            junit allowEmptyResults: true, testResults: 'reports/junit.xml'
        }
    }
}
