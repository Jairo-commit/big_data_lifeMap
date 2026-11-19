#!/usr/bin/env python3
"""Comprueba contra una API en marcha que cada consulta de Power Query (powerbi/queries/*.pq) devuelve lo que el reporte usa.

Cada .pq lleva en su cabecera tres líneas de comentario:
    // URL: /ruta          la ruta de la API que llama
    // QUERY: a=b&c=d      sus parámetros
    // COLUMNS: x,y,z      las columnas que el reporte necesita (están en la tabla de la guía)
Este script pide esa URL, comprueba HTTP 200 y que el CSV traiga el encabezado con todas esas columnas, e informa cuántas filas
hay. Solo usa la biblioteca estándar.

Uso:  python3 powerbi/check_queries.py [--api http://localhost:5000] [--require-rows]
"""

import argparse
import csv
import io
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

QUERIES = Path(__file__).resolve().parent / "queries"


def read_header(path):
    """(URL, QUERY, columnas) de la cabecera de un .pq."""
    text = path.read_text(encoding="utf-8")
    fields = {}
    for key in ("URL", "QUERY", "COLUMNS"):
        match = re.search(rf"^// {key}: (.+)$", text, flags=re.MULTILINE)
        if not match:
            raise SystemExit(f"{path.name}: falta la línea '// {key}: ...' en la cabecera")
        fields[key] = match.group(1).strip()
    return fields["URL"], fields["QUERY"], [c.strip() for c in fields["COLUMNS"].split(",") if c.strip()]


def fetch(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read().decode("utf-8")


def check(api, path, require_rows):
    route, query, columns = read_header(path)
    url = f"{api.rstrip('/')}{route}?{query}"
    try:
        status, content_type, body = fetch(url)
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code} en {url}"
    except (urllib.error.URLError, OSError) as error:
        return False, f"no se pudo llamar a {url}: {error}"
    if status != 200 or "csv" not in content_type:
        return False, f"se esperaba CSV con HTTP 200 y llegó {status} {content_type} ({url})"
    rows = list(csv.reader(io.StringIO(body)))
    header = rows[0] if rows else []
    missing = [c for c in columns if c not in header]
    if missing:
        return False, f"faltan columnas {missing} en {url} (llegaron: {header})"
    n_rows = len(rows) - 1
    if require_rows and n_rows == 0:
        return False, f"sin filas en {url}: falta ejecutar el job que llena esos datos"
    return True, f"{n_rows} filas, {len(header)} columnas ({route})"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", default="http://localhost:5000")
    parser.add_argument("--require-rows", action="store_true", help="falla si alguna tabla llega vacía")
    args = parser.parse_args()

    ok = True
    for path in sorted(QUERIES.glob("*.pq")):
        passed, message = check(args.api, path, args.require_rows)
        ok = ok and passed
        print(("PASS " if passed else "FAIL ") + f"{path.stem:<22} {message}")
    print("\nRESULTADO:", "TODO OK" if ok else "HAY FALLOS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
