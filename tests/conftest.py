import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Las pruebas importan los módulos de spark_batch y la lógica de la API (api_flask/queries.py)
# sin necesitar Spark, MongoDB ni Flask instalados.
sys.path.insert(0, str(ROOT / "spark_batch"))
sys.path.insert(0, str(ROOT / "api_flask"))
