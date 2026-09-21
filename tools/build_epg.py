#!/usr/bin/env python3
"""Construye una guía XMLTV a partir del catálogo público de reposición.

El origen publica dos cosas útiles por canal: el catálogo de los últimos ocho
días (`U7D2`), que es lo que aquí interesa porque casi ninguna guía XMLTV trae
pasado, y una selección de lo que viene (`REJILLA`), que es escasa pero sale
gratis en la misma petición.

Salida: `guia.xml` y `guia.xml.gz`, con lo justo para que funcione una guía --
canales con sus nombres, y programas con inicio, fin, título, episodio, género
y descripción--. El resto de lo que devuelve el origen (paquetes comerciales,
productos, imágenes en varios tamaños) es el 58 % del peso y no se usa.

Sin dependencias: solo biblioteca estándar, para que la acción de GitHub no
tenga que instalar nada.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import gzip
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://ottcache.dof6.com/movistarplus/lg"
CHANNELS_URL = f"{BASE}/DIFUSION/contents/channels?tlsstream=true"
BROWSE_URL = f"{BASE}/contents/browse?profile=DIFUSION&sort=FE&start=1&end=1000&mode={{mode}}&channel={{channel}}"
MODES = ("U7D2", "REJILLA")

TIMEOUT = 60
RETRIES = 3
WORKERS = 8
USER_AGENT = "fullEPG/1.0 (+https://github.com/jopsis/fullEPG)"

# Sufijos que las listas cuelgan del nombre del canal. Se emiten como
# `display-name` adicionales para que un canal escrito «LA 1 HD» en la lista
# empareje con el «LA 1» del origen.
QUALITY_SUFFIXES = ("HD", "FHD", "UHD", "4K", "SD")


def fetch(url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"no se pudo descargar {url}: {last}")


def fetch_json(url: str):
    return json.loads(fetch(url).decode("utf-8"))


def channels() -> list[dict]:
    raw = fetch_json(CHANNELS_URL)
    result = []
    for channel in raw:
        code = (channel.get("CodCadenaTv") or "").strip()
        name = (channel.get("Nombre") or "").strip()
        if not code or not name:
            continue
        result.append({
            "code": code,
            "name": name,
            "logo": logo_of(channel),
        })
    return result


def logo_of(channel: dict) -> str | None:
    for entry in channel.get("Logos") or []:
        uri = entry.get("uri")
        if uri:
            return uri
    return channel.get("Logo") or None


def programmes_of(code: str) -> list[dict]:
    """Los pases de un canal, de los dos catálogos, sin repetir."""
    found: dict[tuple[int, str], dict] = {}
    for mode in MODES:
        try:
            payload = fetch_json(BROWSE_URL.format(mode=mode, channel=code))
        except RuntimeError as error:
            print(f"  aviso: {code}/{mode}: {error}", file=sys.stderr)
            continue
        for content in payload.get("Contenidos") or []:
            editorial = content.get("DatosEditoriales") or {}
            for pase in content.get("Pases") or []:
                programme = normalize(pase, editorial, code)
                if programme:
                    # La clave es el instante y el título: un mismo pase
                    # aparece en los dos catálogos el día en curso.
                    found.setdefault((programme["start"], programme["title"]), programme)
    return sorted(found.values(), key=lambda p: p["start"])


def normalize(pase: dict, editorial: dict, fallback_code: str) -> dict | None:
    start_ms = pase.get("HoraInicio")
    minutes = pase.get("Duracion")
    title = (editorial.get("Titulo") or "").strip()
    if not start_ms or not minutes or not title:
        return None
    try:
        start = int(start_ms) // 1000
        stop = start + int(minutes) * 60
    except (TypeError, ValueError):
        return None
    if stop <= start:
        return None

    canal = pase.get("Canal") or {}
    episode = (editorial.get("TituloEpisodio") or "").strip()
    series = (editorial.get("TituloSerie") or "").strip()
    return {
        "channel": (canal.get("CodCadenaTv") or fallback_code).strip(),
        "start": start,
        "stop": stop,
        "title": series or title,
        "subtitle": episode if series else (episode if episode != title else ""),
        "category": (editorial.get("GeneroComAntena") or "").strip(),
        "rating": rating_of(editorial.get("NivelMoral")),
        "season": editorial.get("Temporada"),
        "episode": editorial.get("NumeroEpisodio"),
    }


def rating_of(value) -> str:
    """La calificación llega como objeto (`{"Id": "+16", ...}`) o como texto."""
    if isinstance(value, dict):
        value = value.get("Id") or value.get("Descripcion") or ""
    return str(value or "").strip()


def xmltv_time(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def esc(value: str) -> str:
    # Los títulos traen `&`, comillas y algún carácter de control suelto.
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    return html.escape(cleaned, quote=False)


def display_names(name: str) -> list[str]:
    """El nombre y sus variantes de calidad, sin repetir.

    El emparejado de los reproductores suele caer al nombre cuando el
    identificador no cuadra, así que cuantas más formas se declaren, más
    canales encuentran su programación.
    """
    names = [name]
    upper = name.upper()
    if not any(upper.endswith(" " + suffix) for suffix in QUALITY_SUFFIXES):
        names += [f"{name} {suffix}" for suffix in QUALITY_SUFFIXES[:3]]
    seen, result = set(), []
    for candidate in names:
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def build(output: Path, limit: int | None = None) -> dict:
    catalogue = channels()
    if limit:
        catalogue = catalogue[:limit]
    print(f"canales en el catálogo: {len(catalogue)}")

    collected: dict[str, list[dict]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(programmes_of, c["code"]): c for c in catalogue}
        for done in concurrent.futures.as_completed(futures):
            channel = futures[done]
            try:
                programmes = done.result()
            except Exception as error:  # noqa: BLE001 - un canal no tumba la guía
                print(f"  aviso: {channel['code']}: {error}", file=sys.stderr)
                continue
            if programmes:
                collected[channel["code"]] = programmes

    by_code = {c["code"]: c for c in catalogue}
    total = sum(len(v) for v in collected.values())
    print(f"canales con programación: {len(collected)}  programas: {total}")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE tv SYSTEM "xmltv.dtd">',
        f'<tv generator-info-name="fullEPG" generator-info-url="https://github.com/jopsis/fullEPG">',
    ]
    # El DTD pide todos los `channel` antes que los `programme`.
    for code in sorted(collected):
        channel = by_code[code]
        lines.append(f'  <channel id="{esc(code)}">')
        for name in display_names(channel["name"]):
            lines.append(f"    <display-name>{esc(name)}</display-name>")
        if channel["logo"]:
            lines.append(f'    <icon src="{esc(channel["logo"])}" />')
        lines.append("  </channel>")

    for code in sorted(collected):
        for programme in collected[code]:
            lines.append(
                f'  <programme start="{xmltv_time(programme["start"])}"'
                f' stop="{xmltv_time(programme["stop"])}" channel="{esc(code)}">'
            )
            lines.append(f"    <title lang=\"es\">{esc(programme['title'])}</title>")
            if programme["subtitle"]:
                lines.append(f"    <sub-title lang=\"es\">{esc(programme['subtitle'])}</sub-title>")
            description = describe(programme)
            if description:
                lines.append(f"    <desc lang=\"es\">{esc(description)}</desc>")
            if programme["category"]:
                lines.append(f"    <category lang=\"es\">{esc(programme['category'])}</category>")
            numbering = episode_num(programme)
            if numbering:
                lines.append(
                    f'    <episode-num system="xmltv_ns">{numbering}</episode-num>'
                )
            if programme["rating"]:
                lines.append(
                    f'    <rating system="ES"><value>{esc(programme["rating"])}</value></rating>'
                )
            lines.append("  </programme>")
    lines.append("</tv>")

    xml = "\n".join(lines) + "\n"
    output.mkdir(parents=True, exist_ok=True)
    plain = output / "guia.xml"
    plain.write_text(xml, encoding="utf-8")
    with gzip.open(output / "guia.xml.gz", "wb", compresslevel=9) as handle:
        handle.write(xml.encode("utf-8"))

    stats = {
        "generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "canales": len(collected),
        "programas": total,
        "bytes_xml": plain.stat().st_size,
        "bytes_gz": (output / "guia.xml.gz").stat().st_size,
    }
    if total:
        starts = [p["start"] for v in collected.values() for p in v]
        stats["desde"] = xmltv_time(min(starts))
        stats["hasta"] = xmltv_time(max(starts))
    (output / "estado.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_index(output, stats)
    return stats


INDEX = """<!doctype html>
<html lang="es">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fullEPG</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.6 system-ui, sans-serif; margin: 0 auto; padding: 2rem 1rem;
         max-width: 44rem; }}
  code {{ background: rgba(128,128,128,.18); padding: .15em .4em; border-radius: .3em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  td, th {{ text-align: left; padding: .35rem .6rem; border-bottom: 1px solid rgba(128,128,128,.3); }}
  a.file {{ display: inline-block; margin-right: 1rem; }}
</style>
<h1>fullEPG</h1>
<p>Guía XMLTV con los <strong>últimos ocho días</strong> de programación, que es
lo que casi ninguna guía trae. Se regenera sola una vez al día.</p>
<p>
  <a class="file" href="guia.xml.gz">guia.xml.gz</a>
  <a class="file" href="guia.xml">guia.xml</a>
  <a class="file" href="estado.json">estado.json</a>
</p>
<table>
  <tr><th>Generada</th><td>{generado}</td></tr>
  <tr><th>Canales</th><td>{canales}</td></tr>
  <tr><th>Programas</th><td>{programas}</td></tr>
  <tr><th>Desde</th><td>{desde}</td></tr>
  <tr><th>Hasta</th><td>{hasta}</td></tr>
  <tr><th>Tamaño</th><td>{mb_gz} MB comprimida · {mb_xml} MB en claro</td></tr>
</table>
<p>Para usarla, da de alta <code>guia.xml.gz</code> como guía EPG en tu
reproductor. El emparejado por nombre funciona con las variantes corrientes
(<code>HD</code>, <code>FHD</code>, <code>UHD</code>).</p>
</html>
"""


def write_index(output: Path, stats: dict) -> None:
    output.joinpath("index.html").write_text(
        INDEX.format(
            generado=stats["generado"],
            canales=stats["canales"],
            programas=stats["programas"],
            desde=stats.get("desde", "-"),
            hasta=stats.get("hasta", "-"),
            mb_gz=f"{stats['bytes_gz'] / 1024 / 1024:.1f}",
            mb_xml=f"{stats['bytes_xml'] / 1024 / 1024:.1f}",
        ),
        encoding="utf-8",
    )


def episode_num(programme: dict) -> str | None:
    """`xmltv_ns` a partir de temporada y episodio, que llegan sucios.

    El origen escribe la temporada como «(T1)», como «1» o como nada, así que
    se extrae el primer número que aparezca y se descarta lo que no lo tenga.
    """
    season = first_number(programme["season"])
    episode = first_number(programme["episode"])
    if episode is None:
        return None
    left = "" if season is None else str(season - 1)
    return f"{left}.{episode - 1}."


def first_number(value) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    number = int(match.group())
    return number if number > 0 else None


def describe(programme: dict) -> str:
    """Primera línea al estilo de las guías corrientes: género y calificación."""
    parts = [p for p in (programme["category"], programme["rating"]) if p]
    if programme["subtitle"] and programme["subtitle"] != programme["title"]:
        parts.append(programme["subtitle"])
    return " | ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="public", type=Path, help="carpeta de salida")
    parser.add_argument("--limit", type=int, help="solo los N primeros canales (pruebas)")
    args = parser.parse_args()

    started = time.time()
    stats = build(args.out, args.limit)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    print(f"en {time.time() - started:.0f} s")
    return 0 if stats["programas"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
