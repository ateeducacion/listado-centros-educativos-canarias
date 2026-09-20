#!/usr/bin/env python3
"""Build stable consumer artefacts from the canonical centres dataset."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "centros.csv"
OUTPUT_DIR = ROOT / "dist"
MIN_JSON = OUTPUT_DIR / "centros.min.json"
DISTANCES_CSV = OUTPUT_DIR / "centros-distancias.csv"
MANIFEST = OUTPUT_DIR / "manifest.json"

DISTANCE_FIELDS = [
    "Codigo",
    "Denominacion",
    "Direccion",
    "Localidad",
    "CodigoPostal",
    "Municipio",
    "Isla",
    "Provincia",
    "Naturaleza",
    "TipoCentro",
    "Longitud",
    "Latitud",
]


def clean(value: Any) -> str:
    """Return a stripped string for a potentially empty value."""
    return "" if value is None else str(value).strip()


def is_active(row: dict[str, str]) -> bool:
    """Return whether a canonical centre is active."""
    return clean(row.get("Activo", "1")).casefold() not in {"0", "false", "no"}


def has_valid_coordinates(row: dict[str, str]) -> bool:
    """Return whether a centre has usable Canary Islands coordinates."""
    try:
        longitude = float(clean(row.get("Longitud")))
        latitude = float(clean(row.get("Latitud")))
    except ValueError:
        return False
    return -19 <= longitude <= -13 and 27 <= latitude <= 30


def sha256(path: Path) -> str:
    """Return a file SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(path: Path = DATASET) -> list[dict[str, str]]:
    """Read the canonical CSV dataset."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_min_json(rows: list[dict[str, str]], destination: Path) -> int:
    """Write the compact catalogue used by form-based consumers."""
    payload = [
        {
            "code": clean(row.get("Codigo")),
            "name": clean(row.get("Denominacion")),
            "island": clean(row.get("Isla")),
            "municipality": clean(row.get("Municipio")),
            "type": clean(row.get("DesEtapaCentro")),
            "active": is_active(row),
        }
        for row in rows
        if clean(row.get("Codigo")) and clean(row.get("Denominacion"))
    ]
    payload.sort(key=lambda item: (str(item["name"]).casefold(), str(item["code"])))
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return len(payload)


def build_distances_csv(rows: list[dict[str, str]], destination: Path) -> int:
    """Write active geolocated centres using the distance-project contract."""
    selected = [row for row in rows if is_active(row) and has_valid_coordinates(row)]
    selected.sort(key=lambda row: clean(row.get("Codigo")))

    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DISTANCE_FIELDS)
        writer.writeheader()
        for row in selected:
            writer.writerow({field: clean(row.get(field)) for field in DISTANCE_FIELDS})
    return len(selected)


def main() -> None:
    """Generate compact, distance and manifest artefacts."""
    rows = load_rows()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    catalogue_count = build_min_json(rows, MIN_JSON)
    distance_count = build_distances_csv(rows, DISTANCES_CSV)
    active_count = sum(1 for row in rows if is_active(row))

    catalogue_updated_at = os.environ.get("CATALOGUE_UPDATED_AT", "").strip()
    catalogue_commit = os.environ.get("CATALOGUE_COMMIT", "").strip()

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "catalogue_updated_at": catalogue_updated_at or None,
        "catalogue_commit": catalogue_commit or None,
        "records": len(rows),
        "active_records": active_count,
        "catalogue_records": catalogue_count,
        "distance_records": distance_count,
        "files": {
            "centros.min.json": {
                "sha256": sha256(MIN_JSON),
                "records": catalogue_count,
            },
            "centros-distancias.csv": {
                "sha256": sha256(DISTANCES_CSV),
                "records": distance_count,
            },
        },
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Exported {catalogue_count} catalogue records and "
        f"{distance_count} geolocated active centres"
    )


if __name__ == "__main__":
    main()
