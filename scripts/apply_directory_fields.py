#!/usr/bin/env python3
"""Turn reviewed directory differences into per-field catalogue corrections."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from directory_diff import CODE_RE, OUTPUT_JSON, SEARCH_URL, clean
from update_data import DIRECTORY_SOURCE, STATUS_FIELDS

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "centre_field_overrides.csv"
FIELDNAMES = ["Codigo", "Campo", "Valor", "Fuente", "FuenteURL"]

# A dependent field is not derived in code: when one of these is corrected the
# companions are written too, so the file states every value it changes.
COMPANIONS = {
    "ZonaInspeccionCodigo": ("ZonaInspeccionNombre", "FuenteZonaInspeccion"),
}
# The published zone name only ever states the province, which the centre code
# already determines: 35 for Las Palmas and 38 for Santa Cruz de Tenerife.
PROVINCE_ZONE_NAMES = {
    "35": "LP0 - Provincia Las Palmas",
    "38": "TF0 - Provincia Santa Cruz de Tenerife",
}


def read_overrides() -> dict[tuple[str, str], dict[str, str]]:
    """Read the corrections already committed, keyed by code and field."""
    if not OUTPUT.exists():
        return {}
    with OUTPUT.open(encoding="utf-8-sig", newline="") as handle:
        return {
            (clean(row["Codigo"]), clean(row["Campo"])): row
            for row in csv.DictReader(handle)
        }


def zone_rows(code: str, zone: str) -> list[tuple[str, str]]:
    """Return the zone identifier and the companions it implies."""
    name = PROVINCE_ZONE_NAMES.get(code[:2], "")
    if not name:
        raise SystemExit(f"Unknown province for centre {code}")
    return [
        ("ZonaInspeccionCodigo", zone),
        ("ZonaInspeccionNombre", name),
        ("FuenteZonaInspeccion", DIRECTORY_SOURCE),
    ]


def main() -> None:
    """Write the corrections for the selected fields of the latest audit."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fields",
        required=True,
        help="Comma-separated catalogue columns to correct from the directory",
    )
    parser.add_argument("--report", type=Path, default=OUTPUT_JSON)
    args = parser.parse_args()

    fields = {value.strip() for value in args.fields.split(",") if value.strip()}
    forbidden = fields & set(STATUS_FIELDS)
    if forbidden:
        raise SystemExit(
            "Lifecycle fields belong to data/centre_overrides.csv: "
            + ", ".join(sorted(forbidden))
        )
    if not args.report.exists():
        raise SystemExit(
            f"{args.report} not found: run scripts/directory_diff.py --scope all first"
        )

    report = json.loads(args.report.read_text(encoding="utf-8"))
    overrides = read_overrides()
    written = 0

    for item in report.get("field_changes", []):
        code = clean(item.get("code"))
        if not CODE_RE.fullmatch(code):
            continue
        url = f"{SEARCH_URL}resultados/detalle?codigo={code}"
        for change in item.get("changes", []):
            field = clean(change.get("field"))
            if field not in fields:
                continue
            value = clean(change.get("directory"))
            pairs = (
                zone_rows(code, value)
                if field in COMPANIONS
                else [(field, value)]
            )
            for name, corrected in pairs:
                overrides[(code, name)] = {
                    "Codigo": code,
                    "Campo": name,
                    "Valor": corrected,
                    "Fuente": DIRECTORY_SOURCE,
                    "FuenteURL": url,
                }
            written += 1

    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(value for _, value in sorted(overrides.items()))

    print(
        f"Applied {written} directory differences: "
        f"{len(overrides)} corrections in {OUTPUT.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
