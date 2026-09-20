#!/usr/bin/env python3
"""Build the enriched centres dataset from official and curated resources."""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import requests

API = "https://datos.canarias.es/catalogos/general/api/3/action/package_show"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = ROOT / "centros.csv"
OUTPUT_JSON = ROOT / "centros.json"
CEP_ASSIGNMENTS = ROOT / "data" / "cep_assignments.csv"
ADDITIONAL_CENTRES = ROOT / "data" / "additional_centres.csv"
CENTRE_OVERRIDES = ROOT / "data" / "centre_overrides.csv"
OFFICIAL_SOURCE = "Datos Abiertos de Canarias"

STATUS_FIELDS = [
    "Activo",
    "FechaAlta",
    "FechaBaja",
    "CodigoSustituidoPor",
    "FuenteCentro",
    "FuenteEstado",
    "FuenteEstadoURL",
]


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


def read_local_csv(path: Path) -> list[dict[str, str]]:
    """Read a curated CSV file from the repository."""
    if not path.exists():
        raise RuntimeError(f"Required curated file not found: {path.relative_to(ROOT)}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def normalized_key(value: Any) -> str:
    """Normalize a text value for stable matching."""
    normalized = unicodedata.normalize("NFKC", clean(value))
    return " ".join(normalized.casefold().split())


def parse_coded_value(value: str) -> tuple[str, str]:
    """Split a value containing an eight-digit centre code."""
    normalized = clean(value)
    if not normalized or normalized.upper() == "SIN ASIGNAR":
        return "", ""

    match = re.search(r"\b(\d{8})\b", normalized)
    if not match:
        return "", normalized

    code = match.group(1)
    name = (normalized[: match.start()] + normalized[match.end() :]).strip(" -")
    return code, name


def load_cep_assignments() -> tuple[
    dict[str, dict[str, str]],
    dict[tuple[str, str], dict[str, str]],
]:
    """Load exact and territorial CEP assignment rules."""
    by_code: dict[str, dict[str, str]] = {}
    by_area: dict[tuple[str, str], dict[str, str]] = {}

    for row in read_local_csv(CEP_ASSIGNMENTS):
        code = clean(row.get("Codigo"))
        island = normalized_key(row.get("Isla"))
        municipality = normalized_key(row.get("Municipio"))

        if code:
            by_code[code] = row
        elif island and municipality:
            by_area[(island, municipality)] = row

    return by_code, by_area


def load_centre_overrides() -> dict[str, dict[str, str]]:
    """Load reviewed lifecycle corrections with explicit provenance."""
    overrides: dict[str, dict[str, str]] = {}
    for row in read_local_csv(CENTRE_OVERRIDES):
        code = clean(row.get("Codigo"))
        if not re.fullmatch(r"\d{8}", code):
            raise RuntimeError(f"Invalid centre override code: {code!r}")
        if code in overrides:
            raise RuntimeError(f"Duplicated centre override code: {code}")
        active = clean(row.get("Activo"))
        if active not in {"0", "1"}:
            raise RuntimeError(f"Invalid Activo value for {code}: {active!r}")
        if not clean(row.get("FuenteEstado")) or not clean(row.get("FuenteEstadoURL")):
            raise RuntimeError(f"Centre override {code} has no state provenance")
        overrides[code] = {key: clean(value) for key, value in row.items()}
    return overrides


def find_cep_assignment(
    row: dict[str, str],
    by_code: dict[str, dict[str, str]],
    by_area: dict[tuple[str, str], dict[str, str]],
) -> dict[str, str]:
    """Resolve a CEP assignment using exact, explicit and territorial data."""
    code = first(row, "Codigo", "CodigoCentro")
    if code in by_code:
        return by_code[code]

    explicit_code, explicit_name = parse_coded_value(first(row, "CentroProfesores"))
    if explicit_code:
        return {
            "CentroProfesoresCodigo": explicit_code,
            "CentroProfesoresNombre": explicit_name,
            "URLWebCEP": first(row, "URLWebCEP"),
        }

    area = (
        normalized_key(first(row, "Isla")),
        normalized_key(first(row, "Municipio")),
    )
    return by_area.get(area, {})


def merge_rows(
    official_rows: list[dict[str, str]],
    additional_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Append curated CEP, CER and EOEP records absent from the official list."""
    merged = [dict(row, FuenteCentro=OFFICIAL_SOURCE) for row in official_rows]
    existing_codes = {first(row, "Codigo", "CodigoCentro") for row in merged}

    for row in additional_rows:
        code = first(row, "Codigo", "CodigoCentro")
        if code and code not in existing_codes:
            merged.append(dict(row, FuenteCentro="data/additional_centres.csv"))
            existing_codes.add(code)

    return merged


def zone_name(row: dict[str, str]) -> str:
    """Return the public designation of an inspection zone."""
    return first(
        row,
        "NombreZonaInspeccion",
        "NombreZona",
        "ZonaInspeccion",
        "DescripcionZonaInspeccion",
        "Descripcion",
        "Territorio",
        "Denominacion",
        "Nombre",
    )


def apply_state(
    item: dict[str, str],
    overrides: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Apply reviewed lifecycle metadata without altering unrelated source fields."""
    defaults = {
        "Activo": "1",
        "FechaAlta": "",
        "FechaBaja": "",
        "CodigoSustituidoPor": "",
        "FuenteEstado": "",
        "FuenteEstadoURL": "",
    }
    for field, value in defaults.items():
        item.setdefault(field, value)
    override = overrides.get(clean(item.get("Codigo")))
    if override:
        for field in defaults:
            item[field] = clean(override.get(field))
    return item


def main() -> None:
    """Generate CSV and JSON artefacts."""
    centres_dataset = package("centros-educativos-de-canarias")
    inspection_dataset = package("zonas-de-inspeccion-educativa-de-canarias")

    official_centres = read_remote_csv(resource_url(centres_dataset, "centros.csv"))
    additional_centres = read_local_csv(ADDITIONAL_CENTRES)
    overrides = load_centre_overrides()
    centre_zones = read_remote_csv(
        resource_url(inspection_dataset, "centros-por-zonas")
    )
    zones = read_remote_csv(resource_url(inspection_dataset, "zonas-de-inspeccion"))

    centres = merge_rows(official_centres, additional_centres)

    zone_names = {
        first(row, "CodigoZonaInspeccion", "CodigoZona", "Codigo"): zone_name(row)
        for row in zones
    }
    zone_by_centre = {
        first(row, "CodigoCentro", "Codigo"): first(
            row, "CodigoZonaInspeccion", "CodigoZona"
        )
        for row in centre_zones
    }
    cep_by_code, cep_by_area = load_cep_assignments()

    source_fields = list(official_centres[0].keys()) if official_centres else []
    for row in additional_centres:
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
        *STATUS_FIELDS,
    ]
    fieldnames = source_fields + [
        field for field in added_fields if field not in source_fields
    ]

    enriched: list[dict[str, str]] = []
    for row in centres:
        code = first(row, "Codigo", "CodigoCentro")
        stage = first(row, "DesEtapaCentro").upper()
        assignment = find_cep_assignment(row, cep_by_code, cep_by_area)
        zone_code = zone_by_centre.get(code, "")
        item = {key: clean(value) for key, value in row.items()}

        if stage == "C.PROFES.":
            assignment = {
                "CentroProfesoresCodigo": code,
                "CentroProfesoresNombre": first(row, "Denominacion"),
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
                    "data/cep_assignments.csv" if assignment else ""
                ),
                "FuenteZonaInspeccion": (
                    "Datos Abiertos de Canarias" if zone_code else ""
                ),
            }
        )
        enriched.append(apply_state(item, overrides))

    enriched.sort(key=lambda row: clean(row.get("Codigo")))

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(enriched)

    OUTPUT_JSON.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Generated {len(enriched)} records")


if __name__ == "__main__":
    main()
