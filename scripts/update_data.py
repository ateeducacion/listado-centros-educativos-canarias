#!/usr/bin/env python3
"""Build the enriched centres dataset from official CKAN resources."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import requests

API = "https://datos.canarias.es/catalogos/general/api/3/action/package_show"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = ROOT / "centros.csv"
OUTPUT_JSON = ROOT / "centros.json"
CEP_ASSIGNMENTS = ROOT / "data" / "cep_assignments.csv"


def package(name: str) -> dict[str, Any]:
    response = requests.get(API, params={"id": name}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(f"CKAN package lookup failed: {name}")
    return payload["result"]


def resource_url(dataset: dict[str, Any], contains: str) -> str:
    for resource in dataset.get("resources", []):
        name = str(resource.get("name", "")).lower()
        url = str(resource.get("url", ""))
        if contains.lower() in name and url:
            return url
    raise RuntimeError(f"Resource not found: {contains}")


def read_remote_csv(url: str) -> list[dict[str, str]]:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return list(csv.DictReader(io.StringIO(response.text)))


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def first(row: dict[str, str], *names: str) -> str:
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return clean(lowered[name.lower()])
    return ""


def load_cep_assignments() -> dict[str, dict[str, str]]:
    if not CEP_ASSIGNMENTS.exists():
        return {}
    with CEP_ASSIGNMENTS.open(encoding="utf-8", newline="") as handle:
        return {
            clean(row["Codigo"]): row
            for row in csv.DictReader(handle)
            if clean(row.get("Codigo"))
        }


def main() -> None:
    centres_dataset = package("centros-educativos-de-canarias")
    inspection_dataset = package("zonas-de-inspeccion-educativa-de-canarias")

    centres = read_remote_csv(resource_url(centres_dataset, "centros.csv"))
    centre_zones = read_remote_csv(resource_url(inspection_dataset, "centros-por-zonas"))
    zones = read_remote_csv(resource_url(inspection_dataset, "zonas-de-inspeccion"))

    zone_names = {
        first(row, "CodigoZonaInspeccion", "CodigoZona", "Codigo"): first(
            row, "ZonaInspeccion", "Denominacion", "Nombre"
        )
        for row in zones
    }
    zone_by_centre = {
        first(row, "CodigoCentro", "Codigo"): first(
            row, "CodigoZonaInspeccion", "CodigoZona"
        )
        for row in centre_zones
    }
    cep = load_cep_assignments()

    source_fields = list(centres[0].keys()) if centres else []
    added_fields = [
        "CentroProfesoresCodigo",
        "CentroProfesoresNombre",
        "URLWebCEP",
        "ZonaInspeccionCodigo",
        "ZonaInspeccionNombre",
        "FuenteCEP",
        "FuenteZonaInspeccion",
    ]
    fieldnames = source_fields + [field for field in added_fields if field not in source_fields]

    enriched: list[dict[str, str]] = []
    for row in centres:
        code = first(row, "Codigo", "CodigoCentro")
        assignment = cep.get(code, {})
        zone_code = zone_by_centre.get(code, "")
        item = {key: clean(value) for key, value in row.items()}
        item.update(
            {
                "CentroProfesoresCodigo": clean(assignment.get("CentroProfesoresCodigo")),
                "CentroProfesoresNombre": clean(assignment.get("CentroProfesoresNombre")),
                "URLWebCEP": clean(assignment.get("URLWebCEP")),
                "ZonaInspeccionCodigo": zone_code,
                "ZonaInspeccionNombre": zone_names.get(zone_code, ""),
                "FuenteCEP": "data/cep_assignments.csv" if assignment else "",
                "FuenteZonaInspeccion": "Datos Abiertos de Canarias" if zone_code else "",
            }
        )
        enriched.append(item)

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(enriched)

    OUTPUT_JSON.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Generated {len(enriched)} records")


if __name__ == "__main__":
    main()
