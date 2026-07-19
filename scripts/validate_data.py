#!/usr/bin/env python3
"""Validate the generated centres dataset."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "centros.csv"

REQUIRED_COLUMNS = {
    "Codigo",
    "Denominacion",
    "CentroProfesoresCodigo",
    "CentroProfesoresNombre",
    "ZonaInspeccionCodigo",
    "ZonaInspeccionNombre",
}


def main() -> None:
    if not DATASET.exists():
        raise SystemExit("centros.csv does not exist")

    with DATASET.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise SystemExit(f"Missing columns: {', '.join(sorted(missing))}")

        seen: set[str] = set()
        rows = 0
        for line_number, row in enumerate(reader, start=2):
            rows += 1
            code = (row.get("Codigo") or "").strip()
            if not code:
                raise SystemExit(f"Missing Codigo at line {line_number}")
            if code in seen:
                raise SystemExit(f"Duplicated Codigo {code} at line {line_number}")
            seen.add(code)

    if rows == 0:
        raise SystemExit("centros.csv contains no records")

    print(f"Validated {rows} records")


if __name__ == "__main__":
    main()
