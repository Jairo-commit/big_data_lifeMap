import sys
from pathlib import Path

# Las pruebas importan los módulos de spark_batch sin necesitar Spark instalado.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "spark_batch"))
