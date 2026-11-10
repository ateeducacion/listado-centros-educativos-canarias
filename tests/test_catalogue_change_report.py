"""Tests for the generated catalogue pull request report."""

from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "catalogue_change_report", ROOT / "scripts" / "catalogue_change_report.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load catalogue_change_report.py")
reporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reporter)


class CatalogueChangeReportTest(unittest.TestCase):
    def make_csv(self, directory: Path, name: str, columns: list[str], rows: list[dict]) -> Path:
        """Write a CSV fixture and return its path."""
        path = directory / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_reports_added_removed_and_changed_centres(self) -> None:
        """Show changes by centre code, not row order."""
        old_columns = ["Codigo", "Denominacion", "Isla", "Telefono"]
        old = {
            "35000011": {"Codigo": "35000011", "Denominacion": "School A", "Isla": "TENERIFE", "Telefono": "111"},
            "35000012": {"Codigo": "35000012", "Denominacion": "School B", "Isla": "LA PALMA", "Telefono": "222"},
        }
        new = {
            "35000011": {"Codigo": "35000011", "Denominacion": "School A", "Isla": "TENERIFE", "Telefono": "333"},
            "35000013": {"Codigo": "35000013", "Denominacion": "School C", "Isla": "EL HIERRO", "Telefono": "444"},
        }
        md = reporter.make_report(old_columns, old, old_columns, new)
        self.assertIn("| Added centres | 1 |", md)
        self.assertIn("| Removed centres | 1 |", md)
        self.assertIn("| Centres with data changes | 1 |", md)
        self.assertIn("### `35000011` — School A", md)
        self.assertIn("| `Telefono` | 111 | 333 |", md)
        self.assertIn("| `35000013` | School C | EL HIERRO |", md)
        self.assertIn("| `35000012` | School B | LA PALMA |", md)

    def test_separates_normalization_from_data_changes(self) -> None:
        """Treat NULL sentinels and trimmed whitespace as formatting only."""
        columns = ["Codigo", "Denominacion", "Fax"]
        old = {"00000001": {"Codigo": "00000001", "Denominacion": "School", "Fax": "NULL"}}
        new = {"00000001": {"Codigo": "00000001", "Denominacion": " School ", "Fax": ""}}
        md = reporter.make_report(columns, old, columns, new)
        self.assertIn("| Centres with data changes | 0 |", md)
        self.assertIn("| Formatting-only field changes | 2 |", md)
        self.assertIn("| `Fax` | 1 |", md)

    def test_flags_removed_populated_columns(self) -> None:
        """Warn when a source column containing data disappears."""
        old_columns = ["Codigo", "Denominacion", "CentroAdscritoEOI"]
        new_columns = ["Codigo", "Denominacion"]
        old = {"00000001": {"Codigo": "00000001", "Denominacion": "School", "CentroAdscritoEOI": "38000000"}}
        new = {"00000001": {"Codigo": "00000001", "Denominacion": "School"}}
        md = reporter.make_report(old_columns, old, new_columns, new)
        self.assertIn("**Warning: columns removed", md)
        self.assertIn("Removed `CentroAdscritoEOI` (1 previously populated records)", md)
        self.assertIn("| Centres with data changes | 0 |", md)

    def test_load_catalogue_rejects_duplicate_codes(self) -> None:
        """Do not silently overwrite duplicate centre codes."""
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_csv(
                Path(directory), "duplicate.csv", ["Codigo", "Denominacion"],
                [{"Codigo": "00000001", "Denominacion": "A"}, {"Codigo": "00000001", "Denominacion": "B"}],
            )
            with self.assertRaisesRegex(ValueError, "duplicate code"):
                reporter.load_catalogue(path)

    def test_escapes_markdown_table_values(self) -> None:
        """Keep arbitrary source values within their Markdown cells."""
        self.assertEqual("A\\|B", reporter.cell("A|B"))
        self.assertEqual("*(empty)*", reporter.cell(""))


if __name__ == "__main__":
    unittest.main()
