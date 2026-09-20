#!/usr/bin/env python3
"""Validate committed and generated catalogue artefacts without network access."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_CSV = ROOT / "centros.csv"
CATALOGUE_JSON = ROOT / "centros.json"
DATA_DIR = ROOT / "data"
DIST_DIR = ROOT / "dist"

CENTRE_CODE_RE = re.compile(r"^\d{8}$")
MIN_JSON_FIELDS = {"code", "name", "island", "municipality", "type", "active"}
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


def fail(message: str) -> None:
    """Abort validation with a readable error."""
    raise SystemExit(message)


def clean(value: Any) -> str:
    """Normalize a scalar value for CSV/JSON comparisons."""
    return "" if value is None else str(value)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read one CSV and reject malformed headers or extra columns."""
    if not path.exists():
        fail(f"Missing CSV file: {path.relative_to(ROOT)}")

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if not fields:
            fail(f"CSV has no header: {path.relative_to(ROOT)}")
        if any(not field for field in fields):
            fail(f"CSV has an empty header: {path.relative_to(ROOT)}")
        if len(fields) != len(set(fields)):
            fail(f"CSV has duplicated headers: {path.relative_to(ROOT)}")

        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                fail(
                    f"CSV has extra columns at {path.relative_to(ROOT)}:"
                    f"{line_number}"
                )
            rows.append({field: clean(row.get(field)) for field in fields})

    return fields, rows


def read_json(path: Path) -> Any:
    """Read one JSON document and report syntax errors clearly."""
    if not path.exists():
        fail(f"Missing JSON file: {path.relative_to(ROOT)}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(
            f"Invalid JSON in {path.relative_to(ROOT)}:"
            f" line {exc.lineno}, column {exc.colno}: {exc.msg}"
        )


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source_csv_files() -> None:
    """Ensure every curated CSV has a structurally valid table."""
    paths = sorted(DATA_DIR.glob("*.csv"))
    if not paths:
        fail("No curated CSV files found under data/")
    for path in paths:
        read_csv(path)


def validate_catalogue_pair() -> tuple[list[str], list[dict[str, str]]]:
    """Ensure centros.csv and centros.json represent the same ordered records."""
    fields, csv_rows = read_csv(CATALOGUE_CSV)
    payload = read_json(CATALOGUE_JSON)
    if not isinstance(payload, list):
        fail("centros.json must contain a JSON array")
    if len(csv_rows) != len(payload):
        fail(
            "centros.csv and centros.json have different record counts: "
            f"{len(csv_rows)} != {len(payload)}"
        )

    field_set = set(fields)
    for index, (csv_row, json_row) in enumerate(zip(csv_rows, payload, strict=True), start=1):
        if not isinstance(json_row, dict):
            fail(f"centros.json record {index} is not an object")
        extra_fields = set(json_row) - field_set
        if extra_fields:
            fail(
                f"centros.json record {index} has fields missing from CSV schema: "
                f"{sorted(extra_fields)}"
            )

        normalized_json = {
            field: clean(json_row.get(field))
            for field in fields
        }
        if csv_row != normalized_json:
            code = csv_row.get("Codigo") or normalized_json.get("Codigo") or f"#{index}"
            changed = [
                field
                for field in fields
                if csv_row.get(field) != normalized_json.get(field)
            ]
            fail(
                f"centros.csv and centros.json differ for {code}: "
                f"{', '.join(changed[:10])}"
            )

    return fields, csv_rows


def active_from_row(row: dict[str, str]) -> bool:
    """Return the catalogue active state with backwards-compatible semantics."""
    return clean(row.get("Activo") or "1").strip().casefold() not in {
        "0",
        "false",
        "no",
        "inactive",
        "inactivo",
    }


def validate_curated_materialization(
    catalogue_rows: list[dict[str, str]],
) -> None:
    """Ensure curated sources and lifecycle overrides reached the catalogue."""
    catalogue = {
        row["Codigo"]: row
        for row in catalogue_rows
        if row.get("Codigo")
    }

    for name in ("additional_centres.csv", "directory_centres.csv"):
        _, curated_rows = read_csv(DATA_DIR / name)
        for row in curated_rows:
            code = clean(row.get("Codigo")).strip()
            if code and code not in catalogue:
                fail(
                    f"Curated centre from data/{name} is missing from committed "
                    f"catalogue: {code}"
                )

    _, field_rows = read_csv(DATA_DIR / "centre_field_overrides.csv")
    for override in field_rows:
        code = clean(override.get("Codigo")).strip()
        field = clean(override.get("Campo")).strip()
        if not code or not field:
            continue
        source = catalogue.get(code)
        if source is None:
            fail(f"Field override is missing from committed catalogue: {code}")
        if clean(source.get(field)) != clean(override.get("Valor")):
            fail(
                f"Field override for {code} did not reach the catalogue: {field} "
                f"is {clean(source.get(field))!r}, expected "
                f"{clean(override.get('Valor'))!r}"
            )
        if field not in clean(source.get("CamposCorregidos")).split(","):
            fail(f"Field override for {code} is not recorded in CamposCorregidos: {field}")

    _, override_rows = read_csv(DATA_DIR / "centre_overrides.csv")
    fields = (
        "Activo",
        "FechaAlta",
        "FechaBaja",
        "CodigoSustituidoPor",
        "FuenteEstado",
        "FuenteEstadoURL",
    )
    for override in override_rows:
        code = clean(override.get("Codigo")).strip()
        if not code:
            continue
        source = catalogue.get(code)
        if source is None:
            fail(
                "Centre override is missing from committed catalogue: "
                f"{code}"
            )
        for field in fields:
            expected = clean(override.get(field))
            actual = clean(source.get(field))
            if actual != expected:
                fail(
                    f"Centre override {code} was not materialized for "
                    f"{field}: {actual!r} != {expected!r}"
                )


def validate_min_json(
    payload: Any,
    catalogue_rows: list[dict[str, str]],
) -> int:
    """Validate the lightweight catalogue contract against the full catalogue."""
    if not isinstance(payload, list):
        fail("dist/centros.min.json must contain a JSON array")

    catalogue = {
        row["Codigo"]: row
        for row in catalogue_rows
        if row.get("Codigo")
    }
    seen: set[str] = set()

    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            fail(f"centros.min.json record {index} is not an object")
        if set(item) != MIN_JSON_FIELDS:
            fail(
                f"centros.min.json record {index} has an unexpected schema: "
                f"{sorted(item)}"
            )

        code = clean(item["code"])
        if not CENTRE_CODE_RE.fullmatch(code):
            fail(f"centros.min.json has invalid centre code: {code!r}")
        if code in seen:
            fail(f"centros.min.json has duplicated centre code: {code}")
        seen.add(code)

        source = catalogue.get(code)
        if source is None:
            fail(f"centros.min.json contains unknown centre code: {code}")

        expected = {
            "code": code,
            "name": clean(source.get("Denominacion")),
            "island": clean(source.get("Isla")),
            "municipality": clean(source.get("Municipio")),
            "type": clean(source.get("DesEtapaCentro")),
            "active": active_from_row(source),
        }
        if item != expected:
            fail(f"centros.min.json differs from centros.csv for {code}")

    if len(payload) != len(catalogue):
        fail(
            "centros.min.json and centros.csv have different usable-code counts: "
            f"{len(payload)} != {len(catalogue)}"
        )
    return len(payload)


def validate_generated(catalogue_rows: list[dict[str, str]]) -> None:
    """Validate generated consumer artefacts and their manifest."""
    min_path = DIST_DIR / "centros.min.json"
    distances_path = DIST_DIR / "centros-distancias.csv"
    manifest_path = DIST_DIR / "manifest.json"

    min_count = validate_min_json(read_json(min_path), catalogue_rows)

    distance_fields, distance_rows = read_csv(distances_path)
    if distance_fields != DISTANCE_FIELDS:
        fail(
            "centros-distancias.csv schema changed: "
            f"{distance_fields!r}"
        )

    catalogue_by_code = {
        row["Codigo"]: row
        for row in catalogue_rows
        if row.get("Codigo")
    }
    seen_distance_codes: set[str] = set()
    for row in distance_rows:
        code = row["Codigo"]
        if code in seen_distance_codes:
            fail(f"centros-distancias.csv has duplicated centre code: {code}")
        seen_distance_codes.add(code)
        source = catalogue_by_code.get(code)
        if source is None:
            fail(f"centros-distancias.csv contains unknown centre code: {code}")
        if not active_from_row(source):
            fail(f"centros-distancias.csv contains inactive centre: {code}")

    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        fail("manifest.json must contain a JSON object")
    if manifest.get("schema_version") != 1:
        fail(f"Unsupported manifest schema: {manifest.get('schema_version')!r}")
    if manifest.get("records") != len(catalogue_rows):
        fail("manifest.json records count does not match centros.csv")
    if manifest.get("active_records") != sum(
        1 for row in catalogue_rows if active_from_row(row)
    ):
        fail("manifest.json active_records does not match centros.csv")
    if manifest.get("catalogue_records") != min_count:
        fail("manifest.json catalogue_records does not match centros.min.json")
    if manifest.get("distance_records") != len(distance_rows):
        fail(
            "manifest.json distance_records does not match centros-distancias.csv"
        )

    files = manifest.get("files")
    if not isinstance(files, dict):
        fail("manifest.json has no files object")
    expected_files = {
        "centros.min.json": min_path,
        "centros-distancias.csv": distances_path,
    }
    for name, path in expected_files.items():
        entry = files.get(name)
        if not isinstance(entry, dict):
            fail(f"manifest.json has no entry for {name}")
        if entry.get("sha256") != sha256(path):
            fail(f"manifest.json SHA-256 does not match {name}")

    print(
        "Validated generated artefacts: "
        f"{min_count} catalogue records, "
        f"{len(distance_rows)} distance records"
    )


def main() -> None:
    """Validate committed catalogue files and optional generated artefacts."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--generated",
        action="store_true",
        help="also validate dist/ consumer artefacts",
    )
    args = parser.parse_args()

    validate_source_csv_files()
    _, catalogue_rows = validate_catalogue_pair()
    validate_curated_materialization(catalogue_rows)
    print(
        "Validated committed artefacts: "
        f"{len(catalogue_rows)} records and "
        f"{len(list(DATA_DIR.glob('*.csv')))} curated CSV files"
    )

    if args.generated:
        validate_generated(catalogue_rows)


if __name__ == "__main__":
    main()
