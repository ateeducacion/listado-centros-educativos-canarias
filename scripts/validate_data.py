#!/usr/bin/env python3
"""Validate the generated centres dataset."""

from __future__ import annotations

import csv
from collections import Counter
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
}

MINIMUM_COUNTS = {
    "records": 1350,
    "cep_assignments": 900,
    "cer_records": 40,
    "eoep_records": 30,
    "inspection_zones": 1000,
}


def main() -> None:
    """Validate structure, uniqueness and enrichment coverage."""
    if not DATASET.exists():
        raise SystemExit("centros.csv does not exist")

    with DATASET.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise SystemExit(f"Missing columns: {', '.join(sorted(missing))}")

        seen: set[str] = set()
        counters: Counter[str] = Counter()

        for line_number, row in enumerate(reader, start=2):
            counters["records"] += 1
            code = (row.get("Codigo") or "").strip()
            if not code:
                raise SystemExit(f"Missing Codigo at line {line_number}")
            if code in seen:
                raise SystemExit(f"Duplicated Codigo {code} at line {line_number}")
            seen.add(code)

            stage = (row.get("DesEtapaCentro") or "").strip().upper()
            if (row.get("CentroProfesoresCodigo") or "").strip():
                counters["cep_assignments"] += 1
            if stage == "CER":
                counters["cer_records"] += 1
            if stage == "EOEP":
                counters["eoep_records"] += 1
            if (row.get("ZonaInspeccionCodigo") or "").strip():
                counters["inspection_zones"] += 1

    failures = [
        f"{name}: {counters[name]} < {minimum}"
        for name, minimum in MINIMUM_COUNTS.items()
        if counters[name] < minimum
    ]
    if failures:
        raise SystemExit("Insufficient dataset coverage: " + "; ".join(failures))

    print(
        "Validated "
        f"{counters['records']} records, "
        f"{counters['cep_assignments']} CEP assignments, "
        f"{counters['cer_records']} CER records, "
        f"{counters['eoep_records']} EOEP records and "
        f"{counters['inspection_zones']} inspection-zone assignments"
    )


if __name__ == "__main__":
    main()
