#!/usr/bin/env python3
"""Compare the canonical catalogue with the operational centre directory."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
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
WIDGETS_URL = (
    "https://www.gobiernodecanarias.org/educacion/centroseducativos/"
    ".content/widgets-buscador-centros-openlayers/"
)
INDEX_URL = WIDGETS_URL + "get-todos-centros.jsp"
MARKERS_URL = WIDGETS_URL + "get-centros.jsp"
DETAIL_URL = WIDGETS_URL + "get-centro-detalle.jsp"
USER_AGENT = "listado-centros-educativos-canarias/1.0"
OFFICIAL_SOURCE = "Datos Abiertos de Canarias"
CODE_RE = re.compile(r"\b\d{8}\b")

# The search application filters an unfiltered query with every value empty.
EMPTY_FILTERS = json.dumps(
    {
        key: {"value": ""}
        for key in (
            "comedor",
            "transporte",
            "desayuno",
            "apertura",
            "vacanteFP",
            "atencionEducativa",
            "provincia",
            "isla",
            "municipio",
            "centro",
            "tipoCentro",
            "naturaleza",
            "grupoEnsenanza",
            "familia",
            "nivel",
            "ciclo",
            "estudio",
            "modalidad",
        )
    }
)

# Fields published in the "Otros" block of a detail card. The inspector name and
# the guard day are deliberately ignored: only the zone identifier is kept.
DETAIL_LABELS = {
    "zona de inspeccion": "inspection_zone_code",
    "cep al que pertenece": "cep_code",
    "centro del profesorado que le corresponde": "cep_code",
    "eoep": "eoep_code",
    "eoep al que pertenece": "eoep_code",
    "centro cer al que pertenece": "cer_code",
    "centro cepa al que pertenece": "cepa_code",
    "centro de destino": "destination_code",
}

COMPARISONS = (
    ("name", "Denominacion", "text"),
    ("stage", "DesEtapaCentro", "text"),
    ("address", "Direccion", "text"),
    ("municipality", "Municipio", "text"),
    ("postal_code", "CodigoPostal", "text"),
    ("phone", "Telefono", "phone"),
    ("fax", "Fax", "phone"),
    ("email", "CorreoElectronico", "email"),
    ("website", "PaginaWeb", "url"),
    ("concert", "Concierto", "text"),
    ("latitude", "Latitud", "coord"),
    ("longitude", "Longitud", "coord"),
    ("cep_code", "CentroProfesoresCodigo", "code"),
    ("cer_code", "CentroCER", "code"),
    ("destination_code", "CentroDestino", "code"),
    ("eoep_code", "EOEP", "code"),
    ("cepa_code", "CentroCepaAlQuePertenece", "code"),
    ("inspection_zone_code", "ZonaInspeccionCodigo", "zone"),
)

SEPARATOR = "\x00"
_thread_local = threading.local()


def collapse(value: str) -> str:
    """Collapse whitespace into one readable value."""
    return " ".join(value.split())


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


def extract_code(value: Any) -> str:
    """Return the first eight-digit centre code found in a value."""
    match = CODE_RE.search(clean(value))
    return match.group(0) if match else ""


def extract_zone(value: Any) -> str:
    """Return the inspection zone identifier, discarding the inspector name."""
    match = re.match(r"\s*(\d+)", clean(value))
    return match.group(1) if match else ""


def fragment_text(fragment: str) -> str:
    """Return the readable text of an HTML fragment, marking line breaks."""
    fragment = re.sub(r"(?i)<br\s*/?>", SEPARATOR, fragment)
    fragment = re.sub(r"(?s)<!--.*?-->", "", fragment)
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def parse_directory_html(document: str) -> dict[str, str]:
    """Parse stable fields from one public directory detail card."""
    document = re.sub(r"(?s)<script.*?</script>", "", document)
    header = re.search(r'(?s)id="centro-cabecera">(.*?)</div>', document)
    if not header:
        return {}

    result: dict[str, str] = {}
    block = header.group(1)
    for pattern, key in (
        (r"(?s)<a[^>]*>(.*?)</a>", "name"),
        (r"(?s)<strong>(.*?)</strong>", "concert"),
    ):
        match = re.search(pattern, block)
        if match:
            result[key] = collapse(fragment_text(match.group(1)))

    match = re.search(r"(?s)</b>\s*-\s*(\d{8})", block)
    if match:
        result["code"] = match.group(1)

    address_block = re.search(r'(?s)id="denominacion">(.*?)</span>', document)
    if address_block:
        lines = [
            collapse(part)
            for part in fragment_text(address_block.group(1)).split(SEPARATOR)
        ]
        lines = [line for line in lines if line]
        if lines and fold(lines[0]).startswith("direccion"):
            lines = lines[1:]
        if lines:
            match = re.match(r"(?s)^(.*?)\s*-\s*(\d{5})$", lines[0])
            if match:
                result["address"] = collapse(match.group(1))
                result["postal_code"] = match.group(2)
            else:
                result["address"] = lines[0]
        if len(lines) > 1:
            # The card prints the municipality under the street address; the
            # locality inside the municipality is not published.
            result["municipality"] = lines[1]

    contact = document[document.find('id="content-1"') :]
    for pattern, key in (
        (r"(?s)<b>Tel</b>\s*-\s*([^<]+)", "phone"),
        (r"(?s)<b>Fax</b>\s*-\s*([^<]+)", "fax"),
        (r'mailto:([^"]+)"', "email"),
        (r'(?s)<a[^>]*href="(https?://[^"]+)"[^>]*>(?!\s*<)', "website"),
    ):
        match = re.search(pattern, contact)
        if match:
            result[key] = collapse(html.unescape(match.group(1)))

    for label, value in re.findall(
        r"(?s)<li[^>]*>\s*<b>(.*?)</b>\s*:\s*(.*?)</li>",
        document,
    ):
        key = DETAIL_LABELS.get(fold(fragment_text(label)))
        if not key or key in result:
            continue
        text = collapse(fragment_text(value))
        result[key] = extract_zone(text) if key.endswith("zone_code") else text

    return result


def normalize_phone(value: Any) -> str:
    """Normalize one or more phone numbers."""
    parts = re.split(r"\s*(?:/|;|,|\by\b)\s*", clean(value), flags=re.IGNORECASE)
    numbers = []
    for part in parts:
        digits = re.sub(r"\D", "", part)
        if len(digits) >= 6:
            numbers.append(digits)
    return "|".join(sorted(numbers))


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


def normalize_coordinate(value: Any) -> str:
    """Round a coordinate to about one metre so precision noise is ignored."""
    raw = clean(value).replace(",", ".")
    if not raw:
        return ""
    try:
        return f"{float(raw):.5f}"
    except ValueError:
        return raw


def comparable(value: Any, kind: str) -> str:
    """Return a stable comparable representation."""
    if kind == "code":
        return extract_code(value)
    if kind == "zone":
        return extract_zone(value)
    if kind == "phone":
        return normalize_phone(value)
    if kind == "email":
        return normalize_email(value)
    if kind == "url":
        return normalize_url(value)
    if kind == "coord":
        return normalize_coordinate(value)
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


def rotating_batch(
    codes: list[str],
    batch_size: int,
    rotation_key: int | None = None,
) -> tuple[list[str], int, int]:
    """Return one deterministic rotating batch of centre codes."""
    if batch_size <= 0 or batch_size >= len(codes):
        return codes, 1, 1

    total_batches = (len(codes) + batch_size - 1) // batch_size
    if rotation_key is None:
        now = datetime.now(UTC).isocalendar()
        rotation_key = (now.year * 53) + now.week

    batch_index = rotation_key % total_batches
    start = batch_index * batch_size
    end = min(start + batch_size, len(codes))
    return codes[start:end], batch_index + 1, total_batches


def select_codes(
    catalogue: dict[str, dict[str, str]],
    scope: str,
    explicit_codes: str,
    directory_codes: set[str] | None = None,
) -> list[str]:
    """Select the codes whose detail card is fetched one by one."""
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
        codes.update(directory_codes or ())
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


def post_json(url: str, data: dict[str, str], timeout: float) -> Any:
    """Post one unfiltered query to a search widget and decode its payload."""
    response = request_session().post(url, data=data, timeout=timeout)
    response.raise_for_status()
    return json.loads(response.text.strip())


def directory_index(timeout: float = 60.0) -> dict[str, dict[str, str]]:
    """Return every centre published by the directory, keyed by code.

    Two unfiltered queries cover the whole directory: the results listing adds
    contact data and the map layer adds coordinates and the centre stage.
    """
    index: dict[str, dict[str, str]] = {}

    listing = post_json(INDEX_URL, {"filtros": EMPTY_FILTERS, "pagina": "1"}, timeout)
    for row in listing.get("centros", []):
        code = clean(row.get("Codigo"))
        if not CODE_RE.fullmatch(code):
            continue
        index[code] = {
            "code": code,
            "name": clean(row.get("Denominacion")),
            "municipality": clean(row.get("Municipio")),
            "address": clean(row.get("Direccion")),
            "phone": clean(row.get("Telefono")),
            "email": clean(row.get("CorreoElectronico")),
        }

    markers = post_json(
        MARKERS_URL,
        {"filtros": EMPTY_FILTERS, "universidades": "false"},
        timeout,
    )
    for row in markers:
        code = clean(row.get("Codigo"))
        if not CODE_RE.fullmatch(code):
            continue
        entry = index.setdefault(code, {"code": code})
        entry.setdefault("name", clean(row.get("Denominacion")))
        entry.update(
            {
                "stage": clean(row.get("DesEtapaCentro")),
                "latitude": clean(row.get("Latitud")),
                "longitude": clean(row.get("Longitud")),
                "destination_code": clean(row.get("CentroDestino")),
            }
        )

    if not index:
        raise RuntimeError("The directory index came back empty")
    return index


def fetch_directory(
    code: str,
    timeout: float = 30.0,
    attempts: int = 1,
) -> dict[str, Any]:
    """Fetch and parse one public directory detail card."""
    last_error = ""
    attempt_count = max(1, min(attempts, 3))
    for attempt in range(attempt_count):
        try:
            response = request_session().get(
                DETAIL_URL,
                params={"codigo": code, "universidades": "false"},
                timeout=timeout,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(
                    f"HTTP {response.status_code}",
                    response=response,
                )

            response.raise_for_status()
            fields = parse_directory_html(response.text)
            if not fields:
                # The widget answers with an empty card for unknown codes.
                return {"code": code, "present": False, "fields": {}, "error": ""}
            if code == fields.get("code"):
                return {
                    "code": code,
                    "present": True,
                    "fields": fields,
                    "error": "",
                }
            last_error = "unexpected_code_in_directory_card"
        except (requests.RequestException, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt + 1 < attempt_count:
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
        directory_value = clean(directory.get(directory_key))
        if not directory_value:
            # A field the directory does not publish is not a discrepancy.
            continue

        catalogue_value = clean(catalogue_row.get(catalogue_key))
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
                    "stage": clean(fields.get("stage")),
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
            "index_url": INDEX_URL,
            "markers_url": MARKERS_URL,
            "detail_url_template": DETAIL_URL + "?codigo={code}",
            "note": (
                "The search widgets answer unfiltered queries with the whole "
                "operational directory, so presence is checked in two requests "
                "and only the detail cards are fetched code by code."
            ),
        },
        "coverage": {
            "complete_for_known_codes": True,
            "new_code_discovery": (
                "The unfiltered index lists every published code, so centres "
                "absent from the catalogue are reported without another source."
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
                "| Código | Denominación | Municipio | Etapa |",
                "|---|---|---|---|",
            ]
        )
        for item in report["directory_only"]:
            lines.append(
                f"| {item['code']} | {item['name']} | "
                f"{item['municipality']} | {item.get('stage', '')} |"
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
            "El buscador público responde a una consulta sin filtros con el "
            "listado completo del directorio operativo. Esa consulta se usa "
            "para comprobar presencia y para detectar códigos que el catálogo "
            "todavía no recoge; las fichas por código sólo se piden para los "
            "centros seleccionados por el alcance.",
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


def fetch_details(
    codes: list[str],
    timeout: float,
    attempts: int,
    workers: int,
    delay: float,
) -> dict[str, dict[str, Any]]:
    """Fetch the detail card of every selected code."""
    results: dict[str, dict[str, Any]] = {}

    if workers == 1:
        for index, code in enumerate(codes):
            results[code] = fetch_directory(code, timeout, attempts)
            if delay > 0 and index + 1 < len(codes):
                time.sleep(delay)
        return results

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_directory, code, timeout, attempts): code
            for code in codes
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                results[code] = future.result()
            except Exception as exc:  # pragma: no cover - defensive
                results[code] = {
                    "code": code,
                    "present": False,
                    "fields": {},
                    "error": f"{type(exc).__name__}: {exc}",
                }
    return results


def build_checks(
    catalogue: dict[str, dict[str, str]],
    index: dict[str, dict[str, str]],
    details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge the bulk index and the fetched detail cards into one check list."""
    checks: list[dict[str, Any]] = []
    for code in sorted(set(catalogue) | set(index) | set(details)):
        detail = details.get(code, {})
        if detail.get("error"):
            checks.append(detail)
            continue

        fields = dict(index.get(code, {}))
        fields.update(detail.get("fields", {}))
        checks.append(
            {
                "code": code,
                "present": code in index or bool(detail.get("present")),
                "fields": fields,
                "error": "",
            }
        )
    return checks


def main() -> None:
    """Compare the catalogue with the public operational directory."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        choices=("candidates", "all"),
        default="candidates",
    )
    parser.add_argument("--codes", default="")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--rotation-key", type=int)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    catalogue = load_catalogue()
    index = directory_index(max(args.timeout, 60.0))

    codes = select_codes(catalogue, args.scope, args.codes, set(index))
    codes, batch_number, batch_count = rotating_batch(
        codes,
        args.batch_size,
        args.rotation_key,
    )
    if args.limit > 0:
        codes = codes[: args.limit]

    workers = max(1, min(args.workers, 8))
    delay = max(0.0, args.delay)
    details = fetch_details(codes, args.timeout, args.attempts, workers, delay)

    report = build_report(catalogue, build_checks(catalogue, index, details), args.scope)
    report["index_count"] = len(index)
    report["detail_count"] = len(details)
    report["batch"] = {
        "number": batch_number,
        "count": batch_count,
        "size": len(codes),
        "delay_seconds": delay,
        "workers": workers,
    }
    write_report(report)
    print(
        "Directory diff: "
        f"{report['checked_count']} checked, "
        f"{report['attention_count']} require review"
    )

    if details and all(check.get("error") for check in details.values()):
        raise SystemExit("All directory detail requests failed")


if __name__ == "__main__":
    main()
