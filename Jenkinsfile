pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Docker Images') {
            steps {
                sh 'docker compose build'
            }
        }

        stage('Run Tests') {
            steps {
                // Ejecutar pruebas unitarias con pytest (validando tasa de cierre)
                sh 'docker run --rm -v ${WORKSPACE}:/app python:3.10-slim sh -c "pip install pytest pymongo && pytest /app/tests/"'
            }
        }

        stage('Deploy') {
            steps {
                // Despliegue automático con docker compose
                sh 'docker compose up -d --build'
            }
        }
    }

    post {
        success {
            echo '¡Despliegue y pruebas completadas exitosamente en la URL pública!'
        }
        failure {
            echo 'El pipeline falló. El despliegue fue bloqueado.'
        }
    }
}
