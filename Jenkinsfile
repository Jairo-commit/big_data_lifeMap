// LifeMap CI/CD (Multibranch Pipeline, see jenkins/JENKINS.md).
// - CI, on pull requests into main and on main: Install → Lint → Test.
// - CD, on main only: Build images → API tests (staging) → Deploy → Ingest → Business life → Spark jobs.
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
        // Spark resources for the full dataset (read by docker-compose.yml). Sized for Jenkins on a PC
        // whose WSL2 has 24 GB (`.wslconfig`): the worker gives 10 GB to the executor, 4 GB go to
        // the driver and the rest is left for MongoDB and the API. The defaults (1 GB worker,
        // 768 MB executor, 2 cores) are for small tests and kill the executor on the full dataset.
        SPARK_WORKER_MEMORY = '12g'
        SPARK_EXECUTOR_MEMORY = '10g'
        SPARK_DRIVER_MEMORY = '4g'
        SPARK_WORKER_CORES = '6'
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
                        // Downloads the Yelp dataset into the image (credential `kaggle`) unless the layer is cached
                        withCredentials([usernamePassword(credentialsId: 'kaggle',
                                usernameVariable: 'KAGGLE_USERNAME', passwordVariable: 'KAGGLE_KEY')]) {
                            sh 'docker compose build dataset'
                        }
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
                        withCredentials([usernamePassword(credentialsId: 'kaggle',
                                usernameVariable: 'KAGGLE_USERNAME', passwordVariable: 'KAGGLE_KEY')]) {
                            sh '$PROD up -d --wait'
                        }
                    }
                }
                stage('Ingest') {
                    steps {
                        // `dataset` + `ingest` start with the stack; this waits until `ingest` has loaded the
                        // full dataset into MongoDB (it exits at once if it was already loaded)
                        withCredentials([usernamePassword(credentialsId: 'kaggle',
                                usernameVariable: 'KAGGLE_USERNAME', passwordVariable: 'KAGGLE_KEY')]) {
                            sh '$PROD up --exit-code-from ingest ingest'
                        }
                    }
                }
                stage('Business life') {
                    steps {
                        // Point 3: days-business, event, censoring and GeoJSON per business (idempotent).
                        // The Spark jobs need these fields.
                        sh '$PROD --profile jobs run --rm business-life'
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
