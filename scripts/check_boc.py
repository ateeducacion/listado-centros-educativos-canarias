#!/usr/bin/env python3
"""Detect centre changes in the BOC that may precede the OpenData dataset."""

from __future__ import annotations

import csv
import html
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from directory_diff import directory_index

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "centros.csv"
OUTPUT_DIR = ROOT / "dist"
OUTPUT_JSON = OUTPUT_DIR / "boc-watch.json"
OUTPUT_MD = OUTPUT_DIR / "boc-watch.md"
RSS_URL = "https://www.gobiernodecanarias.org/boc/feeds/capitulo/otras_resoluciones.rss"
USER_AGENT = "listado-centros-educativos-canarias/1.0"
CENTER_CODE_RE = re.compile(r"\b(?:35|38)\d{6}\b")
GUID_RE = re.compile(r"BOC-A-(\d{4})-(\d+)-(\d+)")
RELEVANT_TERMS = (
    "denominacion especifica",
    "cambio de denominacion",
    "creacion",
    "se crea",
    "supresion",
    "se suprime",
    "transformacion",
    "se transforma",
    "centro educativo",
    "centro docente",
    "colegio",
    "instituto",
    "cifp",
    "ceip",
    "ies",
    "cee",
    "cepa",
    "eoi",
)


class TextExtractor(HTMLParser):
    """Collect readable text nodes from an HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def normalized(value: str) -> str:
    """Return accent-free case-folded text for matching."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.casefold().split())


def is_relevant(text: str) -> bool:
    """Return whether a BOC item may change the centre catalogue."""
    candidate = normalized(text)
    return any(term in candidate for term in RELEVANT_TERMS)


def extract_codes(text: str) -> list[str]:
    """Extract unique Canary Islands educational centre codes."""
    return list(dict.fromkeys(CENTER_CODE_RE.findall(text)))


def text_from_html(document: str) -> str:
    """Return readable text from HTML."""
    parser = TextExtractor()
    parser.feed(document)
    return "\n".join(parser.parts)


def load_catalog(path: Path = DATASET) -> dict[str, dict[str, str]]:
    """Load the canonical dataset keyed by centre code."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            (row.get("Codigo") or "").strip(): row
            for row in csv.DictReader(handle)
            if (row.get("Codigo") or "").strip()
        }


def parse_rss(payload: str) -> list[dict[str, str]]:
    """Parse the BOC RSS feed into a stable list of items."""
    root = ET.fromstring(payload)
    items: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        values = {
            key: (item.findtext(key) or "").strip()
            for key in ("title", "link", "description", "pubDate", "guid")
        }
        items.append(values)
    return items


def publication_url(item: dict[str, str]) -> str:
    """Return the readable URL of one BOC entry.

    The feed publishes a `link` built from the entry position, which the site
    no longer serves. The guid carries the announcement number, which is what
    the public page is named after.
    """
    match = GUID_RE.search(item.get("guid", ""))
    if match:
        year, issue, number = match.groups()
        return f"https://www.gobiernodecanarias.org/boc/{year}/{issue}/{number}.html"
    return (item.get("link") or "").strip()


def is_active(row: dict[str, str]) -> bool:
    """Return whether one canonical catalogue row is active."""
    return (row.get("Activo") or "1").strip().casefold() not in {"0", "false", "no"}


def compare_directory(
    code: str,
    catalog_row: dict[str, str] | None,
    directory: dict[str, str] | None,
) -> list[str]:
    """Describe material discrepancies between the catalogue and directory."""
    issues: list[str] = []
    if directory is not None and catalog_row is None:
        issues.append("missing_from_catalogue")
        return issues
    if catalog_row is None:
        return issues
    if directory is None:
        if is_active(catalog_row):
            issues.append("active_but_missing_from_directory")
        return issues

    catalogue_name = (catalog_row.get("Denominacion") or "").strip()
    directory_name = directory.get("name", "").strip()
    names_differ = (
        catalogue_name
        and directory_name
        and normalized(catalogue_name) != normalized(directory_name)
    )
    if names_differ:
        issues.append("name_differs_from_directory")
    if not is_active(catalog_row):
        issues.append("inactive_but_present_in_directory")
    return issues


def main() -> None:
    """Check recent BOC entries and write a review report without changing data."""
    catalog = load_catalog()
    directory = directory_index()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    response = session.get(RSS_URL, timeout=60)
    response.raise_for_status()
    candidates: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    attention_count = 0

    for item in parse_rss(response.text):
        summary = html.unescape(f"{item['title']}\n{item['description']}")
        if not is_relevant(summary):
            continue

        url = publication_url(item)
        publication_text = summary
        if url:
            # A feed entry may point at a page that is not published yet: keep
            # watching the rest of the feed instead of losing the whole report.
            try:
                publication = session.get(url, timeout=60)
                publication.raise_for_status()
            except requests.RequestException as exc:
                unreadable.append({"url": url, "error": str(exc)})
                continue
            publication_text = text_from_html(publication.text)
            if not is_relevant(publication_text):
                continue

        codes = extract_codes(publication_text)
        if not codes:
            continue

        checks: list[dict[str, Any]] = []
        for code in codes:
            entry = directory.get(code)
            catalog_row = catalog.get(code)
            issues = compare_directory(code, catalog_row, entry)
            attention_count += int(bool(issues))
            checks.append(
                {
                    "code": code,
                    "catalogue_present": catalog_row is not None,
                    "catalogue_active": is_active(catalog_row) if catalog_row else None,
                    "catalogue_name": (catalog_row or {}).get("Denominacion", ""),
                    "directory_present": entry is not None,
                    "directory_name": (entry or {}).get("name", ""),
                    "issues": issues,
                }
            )

        candidates.append(
            {
                "title": item["title"],
                "url": url,
                "published": item["pubDate"],
                "codes": codes,
                "checks": checks,
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "rss_url": RSS_URL,
        "candidate_count": len(candidates),
        "attention_count": attention_count,
        "unreadable_count": len(unreadable),
        "unreadable": unreadable,
        "candidates": candidates,
    }
    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Vigilancia de cambios de centros en el BOC",
        "",
        f"- Publicaciones candidatas: {len(candidates)}",
        f"- Comprobaciones que requieren revisión: {attention_count}",
        f"- Publicaciones no legibles: {len(unreadable)}",
        "",
    ]
    for candidate in candidates:
        lines.extend([f"## {candidate['title']}", "", candidate["url"], ""])
        for check in candidate["checks"]:
            issues = ", ".join(check["issues"]) or "sin discrepancias"
            lines.append(
                f"- `{check['code']}`: {issues}; "
                f"catálogo=`{check['catalogue_name']}`; "
                f"directorio=`{check['directory_name']}`"
            )
        lines.append("")
    OUTPUT_MD.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"BOC watch: {len(candidates)} candidates, {attention_count} checks need review")


if __name__ == "__main__":
    main()
