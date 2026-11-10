#!/usr/bin/env python3
"""Generate a human-readable pull request report for catalogue changes."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

MAX_BODY_LENGTH = 60_000


def load_catalogue(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    """Read a CSV catalogue indexed by the official centre code."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if "Codigo" not in fields or len(set(fields)) != len(fields):
            raise ValueError(f"Invalid catalogue columns in {path}")

        rows: dict[str, dict[str, str]] = {}
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed CSV row at {path}:{line_number}")
            code = row["Codigo"].strip()
            if not code or code in rows:
                raise ValueError(f"Missing or duplicate code at {path}:{line_number}")
            rows[code] = row
    return fields, rows


def comparable(value: str) -> str:
    """Ignore only empty sentinels and surrounding whitespace."""
    stripped = value.strip()
    return "" if stripped.upper() == "NULL" else stripped


def cell(value: str) -> str:
    """Escape a value for use in one Markdown table cell."""
    if not value:
        return "*(empty)*"
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("`", "\\`")
    )


def make_report(
    old_fields: list[str],
    old_rows: dict[str, dict[str, str]],
    new_fields: list[str],
    new_rows: dict[str, dict[str, str]],
) -> str:
    """Render all semantic changes and identify schema/format-only changes."""
    old_columns = set(old_fields)
    new_columns = set(new_fields)
    removed_fields = [field for field in old_fields if field not in new_columns]
    added_fields = [field for field in new_fields if field not in old_columns]
    shared_fields = [field for field in new_fields if field in old_columns]
    new_codes = sorted(new_rows.keys() - old_rows.keys())
    removed_codes = sorted(old_rows.keys() - new_rows.keys())
    formatting = Counter()
    modified: list[tuple[str, str, list[tuple[str, str, str]]]] = []

    for code in sorted(old_rows.keys() & new_rows.keys()):
        old = old_rows[code]
        new = new_rows[code]
        changes = []
        for field in shared_fields:
            previous, current = old[field], new[field]
            if previous == current:
                continue
            if comparable(previous) == comparable(current):
                formatting[field] += 1
            else:
                changes.append((field, previous, current))
        if changes:
            modified.append((code, new.get("Denominacion", code), changes))

    lines = [
        "## Catalogue changes",
        "",
        "Automatically generated from official sources and reviewed repository corrections.",
        "The comparison uses `Codigo` as the stable centre identifier.",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Centres before | {len(old_rows)} |",
        f"| Centres after | {len(new_rows)} |",
        f"| Added centres | {len(new_codes)} |",
        f"| Removed centres | {len(removed_codes)} |",
        f"| Centres with data changes | {len(modified)} |",
        f"| Formatting-only field changes | {sum(formatting.values())} |",
        "",
        "## Schema changes",
        "",
    ]

    if removed_fields:
        lines.append("**Warning: columns removed from the published catalogue.**")
        for field in removed_fields:
            populated = sum(bool(comparable(row[field])) for row in old_rows.values())
            lines.append(f"- Removed `{field}` ({populated} previously populated records)")
    if added_fields:
        for field in added_fields:
            populated = sum(bool(comparable(row[field])) for row in new_rows.values())
            lines.append(f"- Added `{field}` ({populated} populated records)")
    if not removed_fields and not added_fields:
        lines.append("No schema changes.")

    for title, codes, rows in (
        ("Added centres", new_codes, new_rows),
        ("Removed centres", removed_codes, old_rows),
    ):
        lines.extend(["", f"## {title} ({len(codes)})", ""])
        if not codes:
            lines.append("None.")
            continue
        lines.extend(["| Code | Name | Island |", "| --- | --- | --- |"])
        for code in codes:
            row = rows[code]
            lines.append(
                f"| `{code}` | {cell(row.get('Denominacion', ''))} "
                f"| {cell(row.get('Isla', ''))} |"
            )

    lines.extend(["", f"## Modified centres ({len(modified)})", ""])
    if not modified:
        lines.append("None.")
    omitted = 0
    for code, name, changes in modified:
        section = [
            f"### `{code}` — {name}",
            "",
            "| Field | Before | After |",
            "| --- | --- | --- |",
            *(f"| `{field}` | {cell(previous)} | {cell(current)} |" for field, previous, current in changes),
            "",
        ]
        if len("\n".join(lines + section)) > MAX_BODY_LENGTH - 5_000:
            omitted += 1
            continue
        lines.extend(section)
    if omitted:
        lines.append(f"**{omitted} modified centres omitted due to PR description size limits.**")
        lines.append("Consult the CSV diff for the remaining changes.")

    lines.extend(["", "## Formatting-only changes", ""])
    if formatting:
        lines.append("Values differing only by `NULL`/empty representation or surrounding whitespace:")
        lines.extend(["", "| Field | Values changed |", "| --- | ---: |"])
        lines.extend(
            f"| `{field}` | {count} |"
            for field, count in sorted(formatting.items(), key=lambda item: (-item[1], item[0]))
        )
    else:
        lines.append("None.")

    lines.extend(
        [
            "",
            "## Validation and sources",
            "",
            "- `python scripts/update_data.py`",
            "- `python scripts/validate_data.py`",
            "- `python scripts/export_consumers.py`",
            "- `python scripts/check_boc.py` (best-effort BOC watch only)",
            "",
            "Published files: `centros.csv` and `centros.json`. Consumer contracts "
            "are regenerated during GitHub Pages deployment.",
            "",
            "BOC candidate checks never modify the catalogue automatically. "
            "Review this pull request before merging.",
            "",
        ]
    )
    report = "\n".join(lines)
    if len(report) > MAX_BODY_LENGTH:
        raise ValueError("Report exceeds GitHub PR description limit; reduce details")
    return report


def main() -> None:
    """Load the baseline and regenerated CSV and write a PR description."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    old_fields, old_rows = load_catalogue(args.before)
    new_fields, new_rows = load_catalogue(args.after)
    report = make_report(old_fields, old_rows, new_fields, new_rows)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote catalogue change report to {args.output}")


if __name__ == "__main__":
    main()
