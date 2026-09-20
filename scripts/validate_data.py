#!/usr/bin/env python3
"""Validate the generated centres dataset."""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "centros.csv"

REQUIRED_COLUMNS = {
    "Codigo",
    "Denominacion",
    "DesEtapaCentro",
    "CentroCER",
    "EOEP",
    "CentroProfesoresCodigo",
    "CentroProfesoresNombre",
    "ZonaInspeccionCodigo",
    "ZonaInspeccionNombre",
    "Activo",
    "FechaAlta",
    "FechaBaja",
    "CodigoSustituidoPor",
    "FuenteCentro",
    "FuenteEstado",
    "FuenteEstadoURL",
}

MINIMUM_COUNTS = {
    "records": 1350,
    "active_records": 1300,
    "cep_assignments": 900,
    "cer_records": 40,
    "eoep_records": 30,
    "inspection_zones": 1000,
}


def validate_date(value: str, code: str, field: str) -> None:
    """Validate an optional ISO date."""
    if not value:
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid {field} for {code}: {value}") from exc


def main() -> None:
    """Validate structure, uniqueness, lifecycle links and enrichment coverage."""
    if not DATASET.exists():
        raise SystemExit("centros.csv does not exist")

    with DATASET.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise SystemExit(f"Missing columns: {', '.join(sorted(missing))}")

        seen: set[str] = set()
        replacements: list[tuple[str, str]] = []
        counters: Counter[str] = Counter()

        for line_number, row in enumerate(reader, start=2):
            counters["records"] += 1
            code = (row.get("Codigo") or "").strip()
            if not re.fullmatch(r"\d{8}", code):
                raise SystemExit(f"Invalid Codigo {code!r} at line {line_number}")
            if code in seen:
                raise SystemExit(f"Duplicated Codigo {code} at line {line_number}")
            seen.add(code)

            if not (row.get("Denominacion") or "").strip():
                raise SystemExit(f"Missing Denominacion for {code}")

            active = (row.get("Activo") or "").strip()
            if active not in {"0", "1"}:
                raise SystemExit(f"Invalid Activo for {code}: {active!r}")
            if active == "1":
                counters["active_records"] += 1

            validate_date((row.get("FechaAlta") or "").strip(), code, "FechaAlta")
            validate_date((row.get("FechaBaja") or "").strip(), code, "FechaBaja")

            replacement = (row.get("CodigoSustituidoPor") or "").strip()
            if replacement:
                if not re.fullmatch(r"\d{8}", replacement):
                    raise SystemExit(
                        f"Invalid CodigoSustituidoPor for {code}: {replacement!r}"
                    )
                if active != "0":
                    raise SystemExit(
                        f"Active centre {code} cannot be replaced by {replacement}"
                    )
                replacements.append((code, replacement))

            if not (row.get("FuenteCentro") or "").strip():
                raise SystemExit(f"Missing FuenteCentro for {code}")
            state_source = (row.get("FuenteEstado") or "").strip()
            state_url = (row.get("FuenteEstadoURL") or "").strip()
            if bool(state_source) != bool(state_url):
                raise SystemExit(
                    f"Incomplete state provenance for {code}: source and URL must coexist"
                )

            stage = (row.get("DesEtapaCentro") or "").strip().upper()
            if (row.get("CentroProfesoresCodigo") or "").strip():
                counters["cep_assignments"] += 1
            if stage == "CER":
                counters["cer_records"] += 1
            if stage == "EOEP":
                counters["eoep_records"] += 1
            if (row.get("ZonaInspeccionCodigo") or "").strip():
                counters["inspection_zones"] += 1

    for code, replacement in replacements:
        if replacement not in seen:
            raise SystemExit(f"Replacement {replacement} referenced by {code} is missing")

    failures = [
        f"{name}: {counters[name]} < {minimum}"
        for name, minimum in MINIMUM_COUNTS.items()
        if counters[name] < minimum
    ]
    if failures:
        raise SystemExit("Insufficient dataset coverage: " + "; ".join(failures))

    print(
        "Validated "
        f"{counters['records']} records ({counters['active_records']} active), "
        f"{counters['cep_assignments']} CEP assignments, "
        f"{counters['cer_records']} CER records, "
        f"{counters['eoep_records']} EOEP records and "
        f"{counters['inspection_zones']} inspection-zone assignments"
    )


if __name__ == "__main__":
    main()
