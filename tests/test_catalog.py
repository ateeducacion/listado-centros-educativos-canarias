from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
import unittest.mock
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
directory_diff = load_script("directory_diff")
update_data = load_script("update_data")
validate_artifacts = load_script("validate_artifacts")
validate_data = load_script("validate_data")


def name_change(code: str, previous: str, new: str, date: str) -> dict[str, str]:
    return {
        "Codigo": code,
        "DenominacionAnterior": previous,
        "DenominacionNueva": new,
        "Fecha": date,
        "Fuente": "Orden de prueba",
        "FuenteURL": "https://example.invalid/boc",
        "Nota": "",
    }


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

    def test_field_override_replaces_one_value_and_records_it(self) -> None:
        item = update_data.apply_field_overrides(
            {"Codigo": "38016672", "Longitud": "-16275", "Latitud": "28.4686"},
            {"38016672": {"Longitud": "-16.275"}},
        )
        self.assertEqual("-16.275", item["Longitud"])
        self.assertEqual("28.4686", item["Latitud"])
        self.assertEqual("Longitud", item["CamposCorregidos"])

        untouched = update_data.apply_field_overrides({"Codigo": "35000011"}, {})
        self.assertEqual("", untouched["CamposCorregidos"])

    def test_field_override_file_is_checked_against_the_schema(self) -> None:
        with (ROOT / "centros.csv").open(encoding="utf-8-sig", newline="") as handle:
            columns = csv.DictReader(handle).fieldnames or []

        overrides = update_data.load_field_overrides(columns)
        self.assertTrue(overrides)
        for code, corrections in overrides.items():
            self.assertRegex(code, r"^\d{8}$")
            for field in corrections:
                self.assertNotIn(field, update_data.STATUS_FIELDS)

        with self.assertRaises(RuntimeError):
            update_data.load_field_overrides(["Codigo"])

    def test_previous_names_are_listed_newest_first(self) -> None:
        previous = update_data.previous_names(
            [
                name_change(
                    "35001475", "CEE SALVADOR RUEDA", "CEE ROMÁN PÉREZ DÉNIZ", "2021-04-12"
                ),
                name_change(
                    "35001050", "CEIP ANDALUCÍA", "CEIP JOSÉ DEL ROSARIO UMPIÉRREZ", "2002-09-27"
                ),
                name_change(
                    "35001475", "CEE ROMÁN PÉREZ DÉNIZ", "CEE GUINIGUADA", "2026-10-22"
                ),
            ]
        )
        self.assertEqual(
            ["CEE ROMÁN PÉREZ DÉNIZ", "CEE SALVADOR RUEDA"], previous["35001475"]
        )
        self.assertEqual(["CEIP ANDALUCÍA"], previous["35001050"])

    def test_previous_names_keep_a_name_the_centre_later_recovered(self) -> None:
        previous = update_data.previous_names(
            [
                name_change(
                    "35008718", "CEIP BATERÍA DE SAN JUAN", "CEIP ALCORAC HENRÍQUEZ", "2014-09-08"
                ),
                name_change(
                    "35008718", "CEIP ALCORAC HENRÍQUEZ", "CEIP BATERÍA DE SAN JUAN", "2025-06-09"
                ),
            ]
        )
        self.assertEqual(
            ["CEIP ALCORAC HENRÍQUEZ", "CEIP BATERÍA DE SAN JUAN"], previous["35008718"]
        )

    def test_name_history_fills_the_previous_names_column(self) -> None:
        previous = {"35001475": ["CEE ROMÁN PÉREZ DÉNIZ", "CEE SALVADOR RUEDA"]}
        item = update_data.apply_name_history(
            {"Codigo": "35001475", "Denominacion": "CEE GUINIGUADA"}, previous
        )
        self.assertEqual(
            "CEE ROMÁN PÉREZ DÉNIZ | CEE SALVADOR RUEDA", item["DenominacionesAnteriores"]
        )
        self.assertEqual("CEE GUINIGUADA", item["Denominacion"])

        untouched = update_data.apply_name_history({"Codigo": "35000011"}, previous)
        self.assertEqual("", untouched["DenominacionesAnteriores"])

    def test_name_history_rejects_rows_without_code_date_names_or_source(self) -> None:
        valid = name_change("35001475", "CEE ROMÁN PÉREZ DÉNIZ", "CEE GUINIGUADA", "2026-10-22")
        self.assertTrue(update_data.previous_names([valid]))
        for field, value in (
            ("Codigo", "3500147"),
            ("Fecha", ""),
            ("Fecha", "22/10/2026"),
            ("DenominacionAnterior", ""),
            ("DenominacionNueva", ""),
            ("Fuente", ""),
            ("FuenteURL", ""),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                update_data.previous_names([dict(valid, **{field: value})])

    def test_name_history_rejects_a_name_containing_the_separator(self) -> None:
        with self.assertRaises(RuntimeError):
            update_data.previous_names(
                [name_change("35001475", "CEE A | CEE B", "CEE GUINIGUADA", "2026-10-22")]
            )

    def test_name_history_rejects_a_change_that_keeps_the_name(self) -> None:
        with self.assertRaises(RuntimeError):
            update_data.previous_names(
                [name_change("35001475", "CEE GUINIGUADA", "CEE GUINIGUADA", "2026-10-22")]
            )

    def test_name_history_rejects_two_changes_of_a_centre_on_one_date(self) -> None:
        with self.assertRaises(RuntimeError):
            update_data.previous_names(
                [
                    name_change("35001475", "CEE A", "CEE B", "2026-10-22"),
                    name_change("35001475", "CEE B", "CEE C", "2026-10-22"),
                ]
            )

    def test_name_history_file_reaches_the_catalogue(self) -> None:
        previous = update_data.previous_names(
            update_data.read_local_csv(update_data.NAME_HISTORY)
        )
        with (ROOT / "centros.csv").open(encoding="utf-8-sig", newline="") as handle:
            catalogue = {row["Codigo"]: row for row in csv.DictReader(handle)}

        self.assertEqual(set(), set(previous) - set(catalogue))
        for code, row in catalogue.items():
            self.assertEqual(
                " | ".join(previous.get(code, [])),
                row["DenominacionesAnteriores"],
                f"Previous names of {code}",
            )
        self.assertEqual(
            "CEE ROMÁN PÉREZ DÉNIZ | CEE SALVADOR RUEDA",
            catalogue["35001475"]["DenominacionesAnteriores"],
        )

    def test_dataset_validation_requires_the_previous_names_column(self) -> None:
        self.assertIn("DenominacionesAnteriores", validate_data.REQUIRED_COLUMNS)

    def test_artifact_validation_compares_previous_names_with_the_history(self) -> None:
        named = {
            "Codigo": "35001475",
            "DenominacionesAnteriores": "CEE ROMÁN PÉREZ DÉNIZ | CEE SALVADOR RUEDA",
        }
        unnamed = {"Codigo": "35000011", "DenominacionesAnteriores": ""}
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            (data / "centre_name_history.csv").write_text(
                "Codigo,DenominacionAnterior,DenominacionNueva,Fecha,Fuente,FuenteURL,Nota\n"
                "35001475,CEE ROMÁN PÉREZ DÉNIZ,CEE GUINIGUADA,2026-10-22,Orden,"
                "https://example.invalid/2,\n"
                "35001475,CEE SALVADOR RUEDA,CEE ROMÁN PÉREZ DÉNIZ,2021-04-12,Orden,"
                "https://example.invalid/1,\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.object(validate_artifacts, "DATA_DIR", data):
                validate_artifacts.validate_name_history([named, unnamed])

                stale = dict(named, DenominacionesAnteriores="CEE SALVADOR RUEDA")
                with self.subTest("stale column"), self.assertRaises(SystemExit):
                    validate_artifacts.validate_name_history([stale, unnamed])

                invented = dict(unnamed, DenominacionesAnteriores="CEIP INVENTADO")
                with self.subTest("names without history"), self.assertRaises(SystemExit):
                    validate_artifacts.validate_name_history([named, invented])

                with self.subTest("centre missing"), self.assertRaises(SystemExit):
                    validate_artifacts.validate_name_history([unnamed])

    def test_merge_rows_prefers_official_source(self) -> None:
        merged = update_data.merge_rows(
            [{"Codigo": "35000011", "Denominacion": "Official"}],
            [
                {"Codigo": "35000011", "Denominacion": "Curated"},
                {"Codigo": "38017731", "Denominacion": "New"},
            ],
            [
                {"Codigo": "38017731", "Denominacion": "Duplicate"},
                {"Codigo": "35630108", "Denominacion": "Directory only"},
            ],
        )
        self.assertEqual(3, len(merged))
        self.assertEqual(
            update_data.DIRECTORY_SOURCE,
            merged[2]["FuenteCentro"],
        )
        self.assertEqual("Directory only", merged[2]["Denominacion"])
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
                "CentroProfesoresCodigo": "35700471",
                "EOEP": "35702370 - E.O.E.P. GRAN CANARIA NOROESTE",
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
            by_code = {row["code"]: row for row in catalogue}
            self.assertEqual("35700471", by_code["35000011"]["cep"])
            self.assertEqual("", by_code["38002065"]["cep"])
            self.assertEqual("35702370", by_code["35000011"]["eoep"])
            self.assertEqual("", by_code["38002065"]["eoep"])
            with csv_path.open(encoding="utf-8", newline="") as handle:
                exported = list(csv.DictReader(handle))
            self.assertEqual(["35000011"], [row["Codigo"] for row in exported])

    def test_manifest_covers_every_published_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            dataset = temp_path / "centros.csv"
            dataset_json = temp_path / "centros.json"
            min_json = temp_path / "centros.min.json"
            distances = temp_path / "centros-distancias.csv"
            dataset.write_text("Codigo\n35000011\n", encoding="utf-8")
            dataset_json.write_text('[{"Codigo": "35000011"}]', encoding="utf-8")
            min_json.write_text("[]\n", encoding="utf-8")
            distances.write_text("Codigo\n", encoding="utf-8")

            with unittest.mock.patch.multiple(
                export_consumers,
                DATASET=dataset,
                DATASET_JSON=dataset_json,
                MIN_JSON=min_json,
                DISTANCES_CSV=distances,
            ):
                files = export_consumers.published_files(0, 0, 1)
                self.assertEqual(
                    {
                        "centros.csv",
                        "centros.json",
                        "centros.min.json",
                        "centros-distancias.csv",
                    },
                    set(files),
                )
                self.assertEqual(1, files["centros.csv"]["records"])
                self.assertEqual(1, files["centros.json"]["records"])
                self.assertEqual(
                    dataset.stat().st_size, files["centros.csv"]["bytes"]
                )
                self.assertEqual(64, len(files["centros.csv"]["sha256"]))

                dataset_json.unlink()
                self.assertNotIn(
                    "centros.json",
                    export_consumers.published_files(0, 0, 1),
                    "centros.json is optional, as in the Pages workflow",
                )

    def test_directory_parser_reads_a_detail_card(self) -> None:
        document = """
        <div id="centro-cabecera">
            <b> <!--false-->
            <a target="_blank" href="/resultados/detalle/?codigo=38017731">
                CIFP EN ICOD DE LOS VINOS
            </a>
            </b> - 38017731
            - <strong>P&uacute;blico</strong>
        </div>
        <div id="content-1">
          <span id="denominacion">
            <b>Direcci&oacute;n</b><br/>
            C/ SAN AGUST&Iacute;N, 12
            - 38430
            <br/>
            ICOD DE LOS VINOS<br/>
          </span>
          <span id="direccion">
            <b>Tel</b> - 922-123456 y 922-654321<br/>
            <b>Fax</b> - 922-111222<br/>
            <a href="mailto:38017731@gobiernodecanarias.org">correo</a><br/>
          </span>
          <span id="direccion">
            <a target="_blank" href="http://example.org/centro">web</a>
          </span>
        </div>
        <div id="content-4">
          <ul class="listaOtros">
            <li><b>Zona de inspecci&oacute;n</b>: 703-APELLIDO NOMBRE, PERSONA</li>
            <li><b>D&iacute;a de guardia</b>: Martes</li>
            <li><b>CEP al que pertenece</b>: 38700391 - C.PROFES. NORTE DE TENERIFE</li>
            <li><b>EOEP</b>: 38702577 - E.O.E.P. YCODEN-DAUTE</li>
          </ul>
        </div>
        """
        parsed = directory_diff.parse_directory_html(document)
        self.assertEqual("38017731", parsed["code"])
        self.assertEqual("CIFP EN ICOD DE LOS VINOS", parsed["name"])
        self.assertEqual("Público", parsed["concert"])
        self.assertEqual("C/ SAN AGUSTÍN, 12", parsed["address"])
        self.assertEqual("38430", parsed["postal_code"])
        self.assertEqual("ICOD DE LOS VINOS", parsed["municipality"])
        self.assertEqual("922-123456 y 922-654321", parsed["phone"])
        self.assertEqual("922-111222", parsed["fax"])
        self.assertEqual("38017731@gobiernodecanarias.org", parsed["email"])
        self.assertEqual("http://example.org/centro", parsed["website"])
        self.assertEqual("38700391", directory_diff.extract_code(parsed["cep_code"]))
        self.assertEqual("38702577", directory_diff.extract_code(parsed["eoep_code"]))

    def test_directory_parser_drops_the_inspector_name(self) -> None:
        document = """
        <div id="centro-cabecera"><b><a>CEIP X</a></b> - 35000011</div>
        <ul class="listaOtros">
          <li><b>Zona de inspecci&oacute;n</b>: 326-APELLIDO APELLIDO, NOMBRE</li>
        </ul>
        """
        parsed = directory_diff.parse_directory_html(document)
        self.assertEqual("326", parsed["inspection_zone_code"])
        self.assertNotIn("APELLIDO", json.dumps(parsed))

    def test_directory_parser_returns_nothing_for_an_unknown_code(self) -> None:
        self.assertEqual({}, directory_diff.parse_directory_html("<html></html>"))

    def test_directory_checks_merge_the_index_and_the_detail_card(self) -> None:
        checks = directory_diff.build_checks(
            {"35000011": {"Codigo": "35000011"}, "35000022": {"Codigo": "35000022"}},
            {"35000011": {"code": "35000011", "name": "CEIP X", "phone": "928-1"}},
            {
                "35000011": {
                    "code": "35000011",
                    "present": True,
                    "fields": {"website": "http://example.org"},
                    "error": "",
                }
            },
        )
        merged = {check["code"]: check for check in checks}
        self.assertTrue(merged["35000011"]["present"])
        self.assertEqual("CEIP X", merged["35000011"]["fields"]["name"])
        self.assertEqual(
            "http://example.org", merged["35000011"]["fields"]["website"]
        )
        self.assertFalse(merged["35000022"]["present"])

    def test_directory_comparison_normalizes_transport_fields(self) -> None:
        catalogue = {
            "Denominacion": "CEIP EJEMPLO",
            "Telefono": "922-123456 y 922-654321",
            "CorreoElectronico": "CENTRO@GOBIERNODECANARIAS.ORG",
            "PaginaWeb": "http://example.org/centro/",
        }
        directory = {
            "name": "ceip ejemplo",
            "phone": "922 654 321 / 922 123 456",
            "email": "centro@gobiernodecanarias.org",
            "website": "https://example.org/centro",
        }
        self.assertEqual([], directory_diff.compare_fields(catalogue, directory))

        directory["name"] = "CEIP NUEVO NOMBRE"
        changes = directory_diff.compare_fields(catalogue, directory)
        self.assertEqual("Denominacion", changes[0]["field"])

    def test_directory_report_does_not_infer_inactive_state(self) -> None:
        catalogue = {
            "35000011": {
                "Codigo": "35000011",
                "Denominacion": "CEIP EJEMPLO",
                "Activo": "1",
            }
        }
        report = directory_diff.build_report(
            catalogue,
            [
                {
                    "code": "35000011",
                    "present": False,
                    "fields": {},
                    "error": "",
                },
                {
                    "code": "38017731",
                    "present": True,
                    "fields": {
                        "code": "38017731",
                        "name": "CIFP EN ICOD DE LOS VINOS",
                        "municipality": "ICOD DE LOS VINOS",
                        "stage": "CIFP",
                    },
                    "error": "",
                },
            ],
            "candidates",
        )
        missing = report["missing_from_directory"][0]
        self.assertTrue(missing["catalogue_active"])
        self.assertEqual("38017731", report["directory_only"][0]["code"])

    def test_directory_rotating_batch_limits_requests(self) -> None:
        codes = [f"{35000000 + index:08d}" for index in range(320)]
        batch, number, count = directory_diff.rotating_batch(
            codes,
            150,
            rotation_key=1,
        )
        self.assertEqual(150, len(batch))
        self.assertEqual(2, number)
        self.assertEqual(3, count)
        self.assertEqual(codes[150:300], batch)

    def test_directory_explicit_codes_override_scope(self) -> None:
        selected = directory_diff.select_codes(
            {"35000011": {"Codigo": "35000011"}},
            "all",
            "38017731, 35000011, invalid",
        )
        self.assertEqual(["35000011", "38017731"], selected)

    def test_boc_publication_url_comes_from_the_guid(self) -> None:
        self.assertEqual(
            "https://www.gobiernodecanarias.org/boc/2026/179/3175.html",
            check_boc.publication_url(
                {
                    "guid": "BOC-A-2026-179-3175",
                    "link": "https://www.gobiernodecanarias.org/boc/2026/179/006.html",
                }
            ),
        )
        self.assertEqual(
            "https://example.invalid/entry",
            check_boc.publication_url(
                {"guid": "", "link": "https://example.invalid/entry"}
            ),
        )

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

    def test_boc_verified_rename_requires_operational_decision(self) -> None:
        title = (
            "ORDEN por la que se autoriza como denominación específica del centro "
            "“Telde-Profesor Antonio Cabrera Pérez”."
        )
        check = {
            "code": "35016016",
            "catalogue_active": True,
            "catalogue_name": "CIFP EN TELDE",
            "directory_name": "CIFP TELDE-PROFESOR ANTONIO CABRERA PÉREZ",
            "issues": ["name_differs_from_directory"],
        }
        decision = (
            "RESUELVO:\nPrimero.- Autorizar como denominación específica del Centro "
            "Integrado de Formación Profesional en Telde, código 35016016, la de "
            "Centro Integrado de Formación Profesional “Telde-Profesor Antonio Cabrera Pérez”."
        )
        self.assertTrue(check_boc.verified_rename(title, decision, ["35016016"], check))
        self.assertTrue(check_boc.verified_rename(
            title, "Antecedentes: código 35016017. " + decision,
            ["35016017", "35016016"], check
        ))
        self.assertFalse(check_boc.verified_rename(
            title, decision.replace("35016016", "35016016 y 35016017"),
            ["35016016", "35016017"], check
        ))
        self.assertTrue(check_boc.verified_rename(
            title, decision.replace("Primero.-", "Primero. \u2013")
            .replace("“", '"').replace("”", '"'),
            ["35016016"], check
        ))
        self.assertFalse(check_boc.verified_rename(
            title, decision.replace("RESUELVO:", ""), ["35016016"], check
        ))
        self.assertTrue(check_boc.verified_rename(
            title, title + " Centro con código 35016016.", ["35016016"], check
        ))
        self.assertFalse(check_boc.verified_rename(
            title, title + " Centro con código 35016016.", ["35016016", "35016017"], check
        ))
        self.assertFalse(check_boc.verified_rename(
            title, "Centro con código 35016016.", ["35016016"], check
        ))
        self.assertFalse(check_boc.verified_rename(
            title, decision, ["35016016"], dict(check, directory_name="CIFP OTRO")
        ))

    def test_boc_proposal_preserves_existing_overrides(self) -> None:
        check = {"code": "35016016", "directory_name": "CIFP NUEVO", "verified_rename": True}
        candidate = {
            "title": "Order",
            "url": "https://www.gobiernodecanarias.org/boc/2026/233/4040.html",
            "checks": [check],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overrides.csv"
            path.write_text("Codigo,Campo,Valor,Fuente,FuenteURL\n", encoding="utf-8")
            self.assertEqual(1, check_boc.propose_renames([candidate], path))
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual("CIFP NUEVO", rows[0]["Valor"])
            self.assertEqual(candidate["url"], rows[0]["FuenteURL"])
            check["directory_name"] = "CIFP OTRO"
            self.assertEqual(0, check_boc.propose_renames([candidate], path))
            with path.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(rows, list(csv.DictReader(handle)))

    def test_boc_pending_report_lists_only_discrepancies(self) -> None:
        def candidate(issues: list[str]) -> dict:
            return {
                "title": f"ORDEN {len(issues)}",
                "url": "https://example.invalid/boc",
                "checks": [
                    {
                        "code": "38016763",
                        "issues": issues,
                        "catalogue_name": "CIFP EN ADEJE",
                        "directory_name": "CIFP GRAN SUR",
                    }
                ],
            }

        self.assertEqual("", check_boc.pending_report([candidate([])]))
        report = check_boc.pending_report(
            [candidate([]), candidate(["name_differs_from_directory"])]
        )
        self.assertIn("ORDEN 1", report)
        self.assertNotIn("ORDEN 0", report)

    def test_curated_cep_url_wins_over_the_published_legacy_address(self) -> None:
        row = {
            "Codigo": "38000241",
            "CentroProfesores": "38700391 - C.PROFES. NORTE DE TENERIFE",
            "URLWebCEP": "http://www.gobiernodecanarias.org/educacion/cepnortedetenerife",
        }
        canonical = "https://www3.gobiernodecanarias.org/medusa/edublog/cprofesnortedetenerife/"

        assignment = update_data.find_cep_assignment(
            row, {}, {}, {"38700391": canonical}
        )
        self.assertEqual(canonical, assignment["URLWebCEP"])

        without_curated = update_data.find_cep_assignment(row, {}, {}, {})
        self.assertEqual(row["URLWebCEP"], without_curated["URLWebCEP"])

    def test_catalogue_only_publishes_curated_cep_addresses(self) -> None:
        curated = {
            row["URLWebCEP"].strip()
            for row in csv.DictReader(
                (ROOT / "data" / "cep_assignments.csv").open(encoding="utf-8-sig")
            )
            if row["URLWebCEP"].strip()
        }
        published = {
            row["URLWebCEP"]
            for row in json.loads((ROOT / "centros.json").read_text(encoding="utf-8"))
            if row["CentroProfesoresCodigo"]
        }
        self.assertTrue(published)
        self.assertEqual(set(), published - curated)


if __name__ == "__main__":
    unittest.main()
