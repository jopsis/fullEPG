#!/usr/bin/env python3
"""Anota en `estado.json`, en la raíz del repositorio, cómo fue la última
ejecución.

Sirve para dos cosas. La primera es poder mirar de un vistazo si la guía se
está regenerando, sin entrar en Actions. La segunda es menos obvia: GitHub
**desactiva los workflows programados cuando un repositorio lleva 60 días sin
actividad**, y este no recibe commits porque solo publica en Pages. Anotar el
resultado en cada pasada deja un commit diario y el cron no se apaga solo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, help="success, failure, cancelled…")
    parser.add_argument("--run-url", default="", help="enlace a la ejecución")
    parser.add_argument(
        "--stats", default="public/estado.json",
        help="cifras que dejó el conversor, si llegó a escribirlas")
    parser.add_argument("--out", default="estado.json", type=pathlib.Path)
    args = parser.parse_args()

    status: dict = {
        "ejecutado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resultado": args.result,
    }
    if args.run_url:
        status["ejecucion"] = args.run_url

    # Solo si de verdad se generó: en un fallo las cifras serían las de la
    # pasada anterior y darían por buena una guía que no se ha tocado.
    stats = pathlib.Path(args.stats)
    if args.result == "success" and stats.exists():
        try:
            status["guia"] = json.loads(stats.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            status["guia"] = None

    args.out.write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
