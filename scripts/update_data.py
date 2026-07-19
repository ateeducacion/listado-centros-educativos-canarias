#!/usr/bin/env python3
"""Build the enriched centres dataset from official public resources."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import requests

API = "https://datos.canarias.es/catalogos/general/api/3/action/package_show"
SITCAN_CENTRES_URL = "https://opendata.sitcan.es/upload/educacion/centros.csv"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = ROOT / "centros.csv"
OUTPUT_JSON = ROOT / "centros.json"
CEP_ASSIGNMENTS = ROOT / "data" / "cep_assignments.csv"
SUPPORT_SERVICE_TYPES = {"C.PROFES.", "CER", "EOEP"}


def package(name: str) -> dict[str, Any]:
    """Return CKAN package metadata."""
    response = requests.get(API, params={"id": name}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(f"CKAN package lookup failed: {name}")
    return payload["result"]


def resource_url(dataset: dict[str, Any], contains: str) -> str:
    """Find a resource URL by a fragment of its name."""
    for resource in dataset.get("resources", []):
        name = str(resource.get("name", "")).lower()
        url = str(resource.get("url", ""))
        if contains.lower() in name and url:
            return url
    raise RuntimeError(f"Resource not found: {contains}")


def read_remote_csv(url: str) -> list[dict[str, str]]:
    """Download and parse a remote CSV resource."""
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return list(csv.DictReader(io.StringIO(response.text)))


def clean(value: Any) -> str:
    """Return a stripped string for a potentially empty value."""
    return "" if value is None else str(value).strip()


def first(row: dict[str, str], *names: str) -> str:
    """Return the first matching field using case-insensitive names."""
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return clean(lowered[name.lower()])
    return ""


def parse_coded_value(value: str) -> tuple[str, str]:
    """Split values formatted as a name followed by an eight-digit code."""
    normalized = clean(value)
    if not normalized or normalized.upper() == "SIN ASIGNAR":
        return "", ""

    match = re.search(r"\s*-\s*(\d{8})\s*$", normalized)
    if match:
        return match.group(1), normalized[: match.start()].strip()

    match = re.search(r"\b(\d{8})\b", normalized)
    if match:
        name = normalized.replace(match.group(1), "").strip(" -")
        return match.group(1), name

    return "", normalized


def load_local_cep_assignments() -> dict[str, dict[str, str]]:
    """Load optional manually reviewed CEP overrides."""
    if not CEP_ASSIGNMENTS.exists():
        return {}
    with CEP_ASSIGNMENTS.open(encoding="utf-8", newline="") as handle:
        return {
            clean(row["Codigo"]): row
            for row in csv.DictReader(handle)
            if clean(row.get("Codigo"))
        }


def build_sitcan_cep_assignments(
    rows: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Build CEP assignments from the historical SITCAN directory."""
    assignments: dict[str, dict[str, str]] = {}
    cep_urls: dict[str, str] = {}

    for row in rows:
        code = first(row, "Codigo", "CodigoCentro")
        stage = first(row, "DesEtapaCentro").upper()
        if stage == "C.PROFES.":
            cep_urls[code] = first(row, "PaginaWeb", "URLWebCEP")

    for row in rows:
        code = first(row, "Codigo", "CodigoCentro")
        cep_code, cep_name = parse_coded_value(first(row, "CentroProfesores"))
        if code and cep_code:
            assignments[code] = {
                "CentroProfesoresCodigo": cep_code,
                "CentroProfesoresNombre": cep_name,
                "URLWebCEP": first(row, "URLWebCEP") or cep_urls.get(cep_code, ""),
            }

    return assignments


def merge_rows(
    official_rows: list[dict[str, str]],
    sitcan_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Append CEP, CER and EOEP service records absent from the main source."""
    merged = list(official_rows)
    existing_codes = {first(row, "Codigo", "CodigoCentro") for row in merged}

    for row in sitcan_rows:
        code = first(row, "Codigo", "CodigoCentro")
        stage = first(row, "DesEtapaCentro").upper()
        if code and code not in existing_codes and stage in SUPPORT_SERVICE_TYPES:
            merged.append(row)
            existing_codes.add(code)

    return merged


def main() -> None:
    """Generate CSV and JSON artefacts."""
    centres_dataset = package("centros-educativos-de-canarias")
    inspection_dataset = package("zonas-de-inspeccion-educativa-de-canarias")

    official_centres = read_remote_csv(resource_url(centres_dataset, "centros.csv"))
    sitcan_centres = read_remote_csv(SITCAN_CENTRES_URL)
    centre_zones = read_remote_csv(resource_url(inspection_dataset, "centros-por-zonas"))
    zones = read_remote_csv(resource_url(inspection_dataset, "zonas-de-inspeccion"))

    centres = merge_rows(official_centres, sitcan_centres)

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

    cep_assignments = build_sitcan_cep_assignments(sitcan_centres)
    local_assignments = load_local_cep_assignments()
    cep_assignments.update(local_assignments)

    source_fields = list(official_centres[0].keys()) if official_centres else []
    for row in sitcan_centres:
        if first(row, "DesEtapaCentro").upper() in SUPPORT_SERVICE_TYPES:
            for field in row:
                if field not in source_fields:
                    source_fields.append(field)

    added_fields = [
        "CentroProfesoresCodigo",
        "CentroProfesoresNombre",
        "ZonaInspeccionCodigo",
        "ZonaInspeccionNombre",
        "FuenteCEP",
        "FuenteZonaInspeccion",
    ]
    fieldnames = source_fields + [field for field in added_fields if field not in source_fields]

    enriched: list[dict[str, str]] = []
    for row in centres:
        code = first(row, "Codigo", "CodigoCentro")
        stage = first(row, "DesEtapaCentro").upper()
        assignment = cep_assignments.get(code, {})
        zone_code = zone_by_centre.get(code, "")
        item = {key: clean(value) for key, value in row.items()}

        if stage == "C.PROFES.":
            assignment = {
                "CentroProfesoresCodigo": code,
                "CentroProfesoresNombre": re.sub(
                    r"\s*-\s*\d{8}\s*$", "", first(row, "Denominacion")
                ).strip(),
                "URLWebCEP": first(row, "PaginaWeb", "URLWebCEP"),
            }

        item.update(
            {
                "CentroProfesoresCodigo": clean(
                    assignment.get("CentroProfesoresCodigo")
                ),
                "CentroProfesoresNombre": clean(
                    assignment.get("CentroProfesoresNombre")
                ),
                "URLWebCEP": clean(assignment.get("URLWebCEP"))
                or first(row, "URLWebCEP"),
                "ZonaInspeccionCodigo": zone_code,
                "ZonaInspeccionNombre": zone_names.get(zone_code, ""),
                "FuenteCEP": (
                    "SITCAN - Directorio de centros educativos"
                    if assignment and code not in local_assignments
                    else "data/cep_assignments.csv"
                    if code in local_assignments
                    else ""
                ),
                "FuenteZonaInspeccion": (
                    "Datos Abiertos de Canarias" if zone_code else ""
                ),
            }
        )
        enriched.append(item)

    enriched.sort(key=lambda row: clean(row.get("Codigo")))

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
