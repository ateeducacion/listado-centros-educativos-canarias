from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export_consumers = load_script("export_consumers")
check_boc = load_script("check_boc")
update_data = load_script("update_data")


class CatalogueTest(unittest.TestCase):
    def test_apply_state_preserves_default_active_and_applies_override(self) -> None:
        current = update_data.apply_state({"Codigo": "35000011"}, {})
        self.assertEqual("1", current["Activo"])

        corrected = update_data.apply_state(
            {"Codigo": "38002065"},
            {
                "38002065": {
                    "Activo": "0",
                    "FechaAlta": "",
                    "FechaBaja": "2026-08-31",
                    "CodigoSustituidoPor": "38017731",
                    "FuenteEstado": "BOC-A-2026-179-3175",
                    "FuenteEstadoURL": "https://example.invalid/boc",
                }
            },
        )
        self.assertEqual("0", corrected["Activo"])
        self.assertEqual("38017731", corrected["CodigoSustituidoPor"])

    def test_merge_rows_prefers_official_source(self) -> None:
        merged = update_data.merge_rows(
            [{"Codigo": "35000011", "Denominacion": "Official"}],
            [
                {"Codigo": "35000011", "Denominacion": "Curated"},
                {"Codigo": "38017731", "Denominacion": "New"},
            ],
        )
        self.assertEqual(2, len(merged))
        self.assertEqual("Official", merged[0]["Denominacion"])
        self.assertEqual("Datos Abiertos de Canarias", merged[0]["FuenteCentro"])
        self.assertEqual("data/additional_centres.csv", merged[1]["FuenteCentro"])

    def test_cep_assignment_urls_match_canonical_cep_websites(self) -> None:
        with (ROOT / "data" / "additional_centres.csv").open(
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            cep_websites = {
                row["Codigo"].strip(): row["PaginaWeb"].strip()
                for row in csv.DictReader(handle)
                if row["DesEtapaCentro"].strip().upper() == "C.PROFES."
            }

        self.assertEqual(14, len(cep_websites))
        self.assertTrue(all(cep_websites.values()))

        with (ROOT / "data" / "cep_assignments.csv").open(
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            for row in csv.DictReader(handle):
                cep_code = row["CentroProfesoresCodigo"].strip()
                self.assertIn(cep_code, cep_websites)
                self.assertEqual(
                    cep_websites[cep_code],
                    row["URLWebCEP"].strip(),
                    f"CEP URL mismatch for {cep_code}",
                )

    def test_consumer_exports_filter_inactive_and_missing_coordinates(self) -> None:
        rows = [
            {
                "Codigo": "35000011",
                "Denominacion": "Centro activo",
                "Isla": "GRAN CANARIA",
                "Municipio": "AGAETE",
                "DesEtapaCentro": "CEIP",
                "Activo": "1",
                "Longitud": "-15.6",
                "Latitud": "28.1",
                "Direccion": "C/ Uno",
                "Localidad": "AGAETE",
                "CodigoPostal": "35480",
                "Provincia": "Las Palmas",
                "Naturaleza": "Público",
                "TipoCentro": "Docente",
            },
            {
                "Codigo": "38002065",
                "Denominacion": "Centro histórico",
                "Isla": "TENERIFE",
                "Municipio": "ICOD DE LOS VINOS",
                "DesEtapaCentro": "IES",
                "Activo": "0",
                "Longitud": "-16.7",
                "Latitud": "28.3",
            },
            {
                "Codigo": "38702577",
                "Denominacion": "Servicio sin coordenadas",
                "Isla": "TENERIFE",
                "Municipio": "",
                "DesEtapaCentro": "EOEP",
                "Activo": "1",
                "Longitud": "",
                "Latitud": "",
            },
        ]
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            json_path = temp_path / "centros.min.json"
            csv_path = temp_path / "centros-distancias.csv"
            self.assertEqual(3, export_consumers.build_min_json(rows, json_path))
            self.assertEqual(1, export_consumers.build_distances_csv(rows, csv_path))

            catalogue = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertFalse(
                next(row for row in catalogue if row["code"] == "38002065")["active"]
            )
            with csv_path.open(encoding="utf-8", newline="") as handle:
                exported = list(csv.DictReader(handle))
            self.assertEqual(["35000011"], [row["Codigo"] for row in exported])

    def test_boc_detector_extracts_codes_and_compares_names(self) -> None:
        text = (
            "Se crea el CIFP con código 38017731 por transformación del IES "
            "con código 38002065."
        )
        self.assertEqual(["38017731", "38002065"], check_boc.extract_codes(text))
        self.assertTrue(check_boc.is_relevant(text))
        issues = check_boc.compare_directory(
            "38017731",
            {"Denominacion": "CIFP VIEJO", "Activo": "1"},
            {"code": "38017731", "name": "CIFP NUEVO"},
        )
        self.assertIn("name_differs_from_directory", issues)


if __name__ == "__main__":
    unittest.main()
