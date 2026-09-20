#!/usr/bin/env python3
"""Compare the canonical catalogue with the operational centre directory."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "centros.csv"
ADDITIONAL_CENTRES = ROOT / "data" / "additional_centres.csv"
CENTRE_OVERRIDES = ROOT / "data" / "centre_overrides.csv"
BOC_REPORT = ROOT / "dist" / "boc-watch.json"
OUTPUT_DIR = ROOT / "dist"
OUTPUT_JSON = OUTPUT_DIR / "directory-diff.json"
OUTPUT_MD = OUTPUT_DIR / "directory-diff.md"

SEARCH_URL = (
    "https://www.gobiernodecanarias.org/educacion/centroseducativos/"
    "buscador-centros-openlayers/"
)
DETAIL_URL = SEARCH_URL + "resultados/detalle"
USER_AGENT = "listado-centros-educativos-canarias/1.0"
OFFICIAL_SOURCE = "Datos Abiertos de Canarias"
CODE_RE = re.compile(r"\b\d{8}\b")

LABELS = {
    "codigo": "code",
    "denominacion": "name",
    "tipo de centro": "centre_type",
    "direccion": "address",
    "localidad": "locality",
    "municipio": "municipality",
    "provincia": "province",
    "isla": "island",
    "codigo postal": "postal_code",
    "telefonos": "phone",
    "correo electronico": "email",
    "web del centro": "website",
    "naturaleza": "nature",
    "tipologia": "typology",
    "titular": "holder",
    "centro del profesorado que le corresponde": "cep",
    "centro cer": "cer",
    "centro de destino": "destination",
    "eoep al que pertenece": "eoep",
    "codigo zona de inspeccion": "inspection_zone_code",
}

COMPARISONS = (
    ("name", "Denominacion", "text"),
    ("centre_type", "DescripcionEtapaCentro", "text"),
    ("address", "Direccion", "text"),
    ("locality", "Localidad", "text"),
    ("municipality", "Municipio", "text"),
    ("province", "Provincia", "text"),
    ("island", "Isla", "text"),
    ("postal_code", "CodigoPostal", "text"),
    ("phone", "Telefono", "phone"),
    ("email", "CorreoElectronico", "email"),
    ("website", "PaginaWeb", "url"),
    ("nature", "Naturaleza", "text"),
    ("typology", "TipoCentro", "text"),
    ("holder", "Titular", "text"),
    ("cep_code", "CentroProfesoresCodigo", "code"),
    ("cer_code", "CentroCER", "code"),
    ("destination_code", "CentroDestino", "code"),
    ("eoep_code", "EOEP", "code"),
    ("inspection_zone_code", "ZonaInspeccionCodigo", "code"),
)

_thread_local = threading.local()


class DirectoryHtmlParser(HTMLParser):
    """Extract label/value pairs from the public directory detail page."""

    def __init__(self) -> None:
        super().__init__()
        self.pairs: list[tuple[str, str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.term: list[str] | None = None
        self.last_term = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag == "tr":
            self.row = []
        elif tag in {"th", "td"} and self.row is not None:
            self.cell = []
        elif "dt" == tag:
            self.term = []
        elif "dd" == tag and self.last_term:
            self.term = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)
        elif self.term is not None:
            self.term.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self.cell is not None and self.row is not None:
            self.row.append(collapse(self.cell))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            cells = [value for value in self.row if value]
            if len(cells) >= 2:
                self.pairs.append((cells[0], " | ".join(cells[1:])))
            self.row = None
        elif tag == "dt" and self.term is not None:
            self.last_term = collapse(self.term)
            self.term = None
        elif tag == "dd" and self.term is not None and self.last_term:
            self.pairs.append((self.last_term, collapse(self.term)))
            self.term = None


def collapse(parts: list[str]) -> str:
    """Collapse HTML text nodes into one readable value."""
    return " ".join(" ".join(parts).split())


def clean(value: Any) -> str:
    """Return a stripped string for a potentially empty value."""
    return "" if value is None else str(value).strip()


def fold(value: Any) -> str:
    """Normalize text for labels and comparisons."""
    normalized = unicodedata.normalize("NFKD", clean(value))
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return " ".join(normalized.casefold().split())


def label_key(value: str) -> str:
    """Normalize a human-readable field label."""
    return fold(value).rstrip(":").strip()


def extract_code(value: Any) -> str:
    """Return the first eight-digit centre code found in a value."""
    match = CODE_RE.search(clean(value))
    return match.group(0) if match else ""


def parse_directory_html(document: str) -> dict[str, str]:
    """Parse stable fields from one public centre detail page."""
    parser = DirectoryHtmlParser()
    parser.feed(document)

    result: dict[str, str] = {}
    for label, value in parser.pairs:
        canonical = LABELS.get(label_key(label))
        if canonical and canonical not in result:
            result[canonical] = clean(value)

    for source, target in (
        ("cep", "cep_code"),
        ("cer", "cer_code"),
        ("destination", "destination_code"),
        ("eoep", "eoep_code"),
    ):
        if source in result:
            result[target] = extract_code(result[source])

    return result


def normalize_phone(value: Any) -> str:
    """Normalize one or more phone numbers."""
    return "|".join(sorted(re.findall(r"\d{6,}", clean(value))))


def normalize_email(value: Any) -> str:
    """Normalize one or more email addresses."""
    emails = re.findall(r"[^\s,;]+@[^\s,;]+", clean(value).casefold())
    return "|".join(sorted(emails))


def normalize_url(value: Any) -> str:
    """Normalize a URL while ignoring HTTP versus HTTPS."""
    raw = clean(value)
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    base = parsed.netloc.casefold() + parsed.path.rstrip("/").casefold()
    return base + (f"?{parsed.query}" if parsed.query else "")


def comparable(value: Any, kind: str) -> str:
    """Return a stable comparable representation."""
    if kind == "code":
        return extract_code(value)
    if kind == "phone":
        return normalize_phone(value)
    if kind == "email":
        return normalize_email(value)
    if kind == "url":
        return normalize_url(value)
    return fold(value)


def load_csv(path: Path) -> list[dict[str, str]]:
    """Read a local CSV file."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_catalogue(path: Path = CATALOGUE) -> dict[str, dict[str, str]]:
    """Load the canonical catalogue keyed by official code."""
    return {
        clean(row.get("Codigo")): row
        for row in load_csv(path)
        if clean(row.get("Codigo"))
    }


def load_boc_codes(path: Path = BOC_REPORT) -> set[str]:
    """Load centre codes detected in the latest BOC report."""
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    codes: set[str] = set()
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        for code in candidate.get("codes", []):
            value = clean(code)
            if CODE_RE.fullmatch(value):
                codes.add(value)
    return codes


def candidate_codes(catalogue: dict[str, dict[str, str]]) -> set[str]:
    """Return codes worth checking on every catalogue refresh."""
    codes = load_boc_codes()

    for path in (ADDITIONAL_CENTRES, CENTRE_OVERRIDES):
        for row in load_csv(path):
            code = clean(row.get("Codigo"))
            if CODE_RE.fullmatch(code):
                codes.add(code)

    for code, row in catalogue.items():
        if clean(row.get("FuenteCentro")) != OFFICIAL_SOURCE:
            codes.add(code)
        if clean(row.get("FuenteEstado")) or clean(row.get("Activo")) == "0":
            codes.add(code)

    return codes


def select_codes(
    catalogue: dict[str, dict[str, str]],
    scope: str,
    explicit_codes: str,
) -> list[str]:
    """Select codes for a candidate or full comparison."""
    if explicit_codes:
        values = {
            value.strip()
            for value in explicit_codes.split(",")
            if CODE_RE.fullmatch(value.strip())
        }
        if not values:
            raise ValueError("--codes did not contain valid eight-digit codes")
        return sorted(values)

    codes = candidate_codes(catalogue)
    if scope == "all":
        codes.update(catalogue)
    if not codes:
        raise RuntimeError("No centre codes selected for directory comparison")
    return sorted(codes)


def request_session() -> requests.Session:
    """Return one reusable requests session per worker thread."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        _thread_local.session = session
    return session


def fetch_directory(code: str, timeout: float = 30.0) -> dict[str, Any]:
    """Fetch and parse one public directory detail page."""
    last_error = ""
    for attempt in range(3):
        try:
            response = request_session().get(
                DETAIL_URL,
                params={"codigo": code},
                timeout=timeout,
            )
            if response.status_code == 404:
                return {"code": code, "present": False, "fields": {}, "error": ""}
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(
                    f"HTTP {response.status_code}",
                    response=response,
                )

            response.raise_for_status()
            fields = parse_directory_html(response.text)
            if code == fields.get("code"):
                return {
                    "code": code,
                    "present": True,
                    "fields": fields,
                    "error": "",
                }

            page_text = fold(response.text)
            if "no se han encontrado" in page_text or "centro no encontrado" in page_text:
                return {
                    "code": code,
                    "present": False,
                    "fields": fields,
                    "error": "",
                }

            if "ha ocurrido un error" in page_text or "validation error" in page_text:
                last_error = "directory_application_error"
            else:
                last_error = "unparseable_directory_response"
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < 2:
            time.sleep(0.5 * (2**attempt))

    return {
        "code": code,
        "present": False,
        "fields": {},
        "error": last_error or "unknown_directory_error",
    }


def compare_fields(
    catalogue_row: dict[str, str],
    directory: dict[str, str],
) -> list[dict[str, str]]:
    """Compare stable fields exposed by both sources."""
    changes: list[dict[str, str]] = []
    for directory_key, catalogue_key, kind in COMPARISONS:
        if directory_key not in directory:
            continue

        catalogue_value = clean(catalogue_row.get(catalogue_key))
        directory_value = clean(directory.get(directory_key))
        if comparable(catalogue_value, kind) == comparable(directory_value, kind):
            continue

        changes.append(
            {
                "field": catalogue_key,
                "catalogue": catalogue_value,
                "directory": directory_value,
            }
        )
    return changes


def build_report(
    catalogue: dict[str, dict[str, str]],
    checks: list[dict[str, Any]],
    scope: str,
) -> dict[str, Any]:
    """Build the machine-readable diff report."""
    directory_only: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    field_changes: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    present_count = 0

    for check in sorted(checks, key=lambda item: item["code"]):
        code = str(check["code"])
        row = catalogue.get(code)

        if check.get("error"):
            errors.append({"code": code, "error": clean(check["error"])})
            continue

        if not check.get("present"):
            if row is not None:
                missing.append(
                    {
                        "code": code,
                        "name": clean(row.get("Denominacion")),
                        "catalogue_active": clean(row.get("Activo", "1")) != "0",
                    }
                )
            continue

        present_count += 1
        fields = check.get("fields", {})
        if not isinstance(fields, dict):
            errors.append({"code": code, "error": "invalid_parsed_fields"})
            continue

        if row is None:
            directory_only.append(
                {
                    "code": code,
                    "name": clean(fields.get("name")),
                    "municipality": clean(fields.get("municipality")),
                    "island": clean(fields.get("island")),
                }
            )
            continue

        changes = compare_fields(row, fields)
        if changes:
            field_changes.append(
                {
                    "code": code,
                    "name": clean(row.get("Denominacion")),
                    "changes": changes,
                }
            )

    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "scope": scope,
        "source": {
            "search_url": SEARCH_URL,
            "detail_url_template": DETAIL_URL + "?codigo={code}",
            "bulk_operational_endpoint": None,
            "bulk_endpoint_note": (
                "The search application uses internal CKAN DataStore resources "
                "that are not a stable public contract."
            ),
        },
        "coverage": {
            "complete_for_known_codes": scope == "all",
            "new_code_discovery": (
                "New codes require another reviewed source, such as the BOC "
                "watch, until a stable public bulk operational index exists."
            ),
        },
        "checked_count": len(checks),
        "present_count": present_count,
        "missing_count": len(missing),
        "field_change_count": len(field_changes),
        "directory_only_count": len(directory_only),
        "error_count": len(errors),
        "attention_count": (
            len(missing) + len(field_changes) + len(directory_only) + len(errors)
        ),
        "directory_only": directory_only,
        "missing_from_directory": missing,
        "field_changes": field_changes,
        "errors": errors,
    }


def markdown_report(report: dict[str, Any]) -> str:
    """Render the diff as Markdown."""
    lines = [
        "# Comparación con el directorio operativo de centros",
        "",
        f"- Alcance: {report['scope']}",
        f"- Códigos comprobados: {report['checked_count']}",
        f"- Fichas encontradas: {report['present_count']}",
        f"- Códigos no encontrados: {report['missing_count']}",
        f"- Centros con diferencias: {report['field_change_count']}",
        f"- Códigos solo en directorio: {report['directory_only_count']}",
        f"- Errores de consulta: {report['error_count']}",
        "",
        "> La presencia o ausencia en el directorio no cambia automáticamente "
        "el estado Activo/Inactivo. Las bajas requieren una fuente explícita.",
        "",
    ]

    if report["directory_only"]:
        lines.extend(
            [
                "## Códigos del directorio ausentes del catálogo",
                "",
                "| Código | Denominación | Municipio | Isla |",
                "|---|---|---|---|",
            ]
        )
        for item in report["directory_only"]:
            lines.append(
                f"| {item['code']} | {item['name']} | "
                f"{item['municipality']} | {item['island']} |"
            )
        lines.append("")

    if report["missing_from_directory"]:
        lines.extend(
            [
                "## Códigos del catálogo no encontrados en el directorio",
                "",
                "| Código | Denominación | Activo en catálogo |",
                "|---|---|---|",
            ]
        )
        for item in report["missing_from_directory"]:
            active = "sí" if item["catalogue_active"] else "no"
            lines.append(f"| {item['code']} | {item['name']} | {active} |")
        lines.append("")

    if report["field_changes"]:
        lines.extend(["## Diferencias de campos", ""])
        for item in report["field_changes"]:
            lines.append(f"### {item['code']} · {item['name']}")
            lines.extend(
                [
                    "",
                    "| Campo | Catálogo | Directorio |",
                    "|---|---|---|",
                ]
            )
            for change in item["changes"]:
                catalogue_value = clean(change["catalogue"]).replace("|", "\\|")
                directory_value = clean(change["directory"]).replace("|", "\\|")
                lines.append(
                    f"| {change['field']} | {catalogue_value} | "
                    f"{directory_value} |"
                )
            lines.append("")

    if report["errors"]:
        lines.extend(["## Errores de consulta", ""])
        for item in report["errors"]:
            lines.append(f"- {item['code']}: {item['error']}")
        lines.append("")

    lines.extend(
        [
            "## Cobertura",
            "",
            "El directorio público expone fichas estables por código. La búsqueda "
            "global usa una implementación CKAN interna, pero no se ha identificado "
            "un índice operacional masivo público y estable. El modo all es "
            "exhaustivo para los códigos conocidos; las altas nuevas dependen de "
            "detectores como BOC hasta disponer de un índice público estable.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any]) -> None:
    """Write JSON, Markdown and the optional Actions summary."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown = markdown_report(report)
    OUTPUT_MD.write_text(markdown, encoding="utf-8")

    summary = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(markdown)


def main() -> None:
    """Compare selected codes with the public operational directory."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        choices=("candidates", "all"),
        default="candidates",
    )
    parser.add_argument("--codes", default="")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    catalogue = load_catalogue()
    codes = select_codes(catalogue, args.scope, args.codes)
    if args.limit > 0:
        codes = codes[: args.limit]

    checks: list[dict[str, Any]] = []
    workers = max(1, min(args.workers, 8))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_directory, code, args.timeout): code
            for code in codes
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                checks.append(future.result())
            except Exception as exc:  # pragma: no cover
                checks.append(
                    {
                        "code": code,
                        "present": False,
                        "fields": {},
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    report = build_report(catalogue, checks, args.scope)
    write_report(report)
    print(
        "Directory diff: "
        f"{report['checked_count']} checked, "
        f"{report['attention_count']} require review"
    )

    if checks and report["error_count"] == len(checks):
        raise SystemExit("All directory requests failed")


if __name__ == "__main__":
    main()
