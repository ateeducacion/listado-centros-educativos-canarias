#!/usr/bin/env python3
"""Build the curated file of centres published only by the operational directory."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from directory_diff import (
    CODE_RE,
    clean,
    directory_index,
    fetch_details,
    fold,
    load_catalogue,
    load_csv,
)
from update_data import DIRECTORY_SOURCE

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "directory_centres.csv"

FIELDNAMES = [
    "Codigo",
    "DesEtapaCentro",
    "Denominacion",
    "Direccion",
    "Localidad",
    "CodigoPostal",
    "Municipio",
    "Isla",
    "Provincia",
    "Telefono",
    "Fax",
    "CorreoElectronico",
    "PaginaWeb",
    "Naturaleza",
    "TipoCentro",
    "Concierto",
    "Longitud",
    "Latitud",
    "CentroDestino",
    "CentroCepaAlQuePertenece",
    "EOEP",
    "CentroCER",
    "ZonaInspeccionCodigo",
]

# Every centre in this file is a public unit of the Canary Islands education
# system, so the holder and the centre type never vary in practice.
TIPO_CENTRO = "Docente"


def territory(catalogue: dict[str, dict[str, str]]) -> dict[str, tuple[str, str]]:
    """Map each known municipality to its island and province."""
    mapping: dict[str, tuple[str, str]] = {}
    for row in catalogue.values():
        municipality = fold(row.get("Municipio"))
        island = clean(row.get("Isla"))
        province = clean(row.get("Provincia"))
        if municipality and island and province:
            mapping.setdefault(municipality, (island, province))
    return mapping


def build_row(
    code: str,
    fields: dict[str, str],
    places: dict[str, tuple[str, str]],
) -> dict[str, str]:
    """Turn one parsed directory card into a curated catalogue row."""
    municipality = clean(fields.get("municipality"))
    island, province = places.get(fold(municipality), ("", ""))
    concert = clean(fields.get("concert"))

    return {
        "Codigo": code,
        "DesEtapaCentro": clean(fields.get("stage")),
        "Denominacion": clean(fields.get("name")),
        "Direccion": clean(fields.get("address")),
        "Localidad": "",
        "CodigoPostal": clean(fields.get("postal_code")),
        "Municipio": municipality,
        "Isla": island,
        "Provincia": province,
        "Telefono": clean(fields.get("phone")),
        "Fax": clean(fields.get("fax")),
        "CorreoElectronico": clean(fields.get("email")),
        "PaginaWeb": clean(fields.get("website")),
        "Naturaleza": "Público" if concert == "Público" else "Privado",
        "TipoCentro": TIPO_CENTRO,
        "Concierto": concert,
        "Longitud": clean(fields.get("longitude")),
        "Latitud": clean(fields.get("latitude")),
        "CentroDestino": clean(fields.get("destination_code")),
        "CentroCepaAlQuePertenece": clean(fields.get("cepa_code")),
        "EOEP": clean(fields.get("eoep_code")),
        "CentroCER": clean(fields.get("cer_code")),
        "ZonaInspeccionCodigo": clean(fields.get("inspection_zone_code")),
    }


def main() -> None:
    """Fetch the directory-only centres and write the curated CSV."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--attempts", type=int, default=2)
    args = parser.parse_args()

    catalogue = load_catalogue()
    index = directory_index(max(args.timeout, 60.0))
    # A code already imported from the directory is refreshed, not skipped:
    # the catalogue this script reads is the one it feeds.
    codes = sorted(
        code
        for code in index
        if clean(catalogue.get(code, {}).get("FuenteCentro")) in ("", DIRECTORY_SOURCE)
    )
    if not codes:
        print("The catalogue already covers every directory code")
        return

    details = fetch_details(
        codes,
        args.timeout,
        args.attempts,
        max(1, min(args.workers, 8)),
        max(0.0, args.delay),
    )

    rows: list[dict[str, str]] = []
    failures: list[str] = []
    for code in codes:
        detail = details.get(code, {})
        if detail.get("error") or not detail.get("present"):
            failures.append(code)
            continue
        fields = dict(index[code])
        fields.update(detail["fields"])
        row = build_row(code, fields, territory(catalogue))
        if not CODE_RE.fullmatch(row["Codigo"]) or not row["Denominacion"]:
            failures.append(code)
            continue
        rows.append(row)

    if failures:
        raise SystemExit(
            "Could not read a usable directory card for: " + ", ".join(failures)
        )

    # A centre that leaves the directory is kept: a removal needs a reviewed
    # source in data/centre_overrides.csv, never the silence of this script.
    fetched = {row["Codigo"] for row in rows}
    kept = [row for row in load_csv(OUTPUT) if row["Codigo"] not in fetched] if (
        OUTPUT.exists()
    ) else []
    if kept:
        print(
            "Kept "
            f"{len(kept)} centres no longer published by the directory: "
            + ", ".join(row["Codigo"] for row in kept)
        )
    rows = sorted(rows + kept, key=lambda row: row["Codigo"])

    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} directory-only centres to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
