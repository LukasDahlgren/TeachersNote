#!/usr/bin/env python3
"""Collect DSV course/program catalog data from Stockholm University."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

BASE_URL = "https://www.su.se"
CATALOG_URL = f"{BASE_URL}/utbildning/utbildningskatalog"
DSV_INSTITUTION_NAME = "Institutionen för data- och systemvetenskap"
DEFAULT_TIMEOUT = 30

PAGE_ID_RE = re.compile(r"pageId:\s*'([^']+)'")
EDU_SEARCH_PORTLET_RE = re.compile(
    r"AppRegistry\.registerApp\(\{[^}]*portletId:'([^']+)'[^}]*webAppId:'educationSearch'"
)
INSTITUTION_RE = re.compile(
    r'"organisation"\s*:\s*\{[^{}]*"name"\s*:\s*"([^"]+)"', re.IGNORECASE
)
STRICT_COURSE_CODE_RE = re.compile(r"(?i)\b([A-Z]{2,4}\d{2,4}[A-Z]?)\b")
OPTIONAL_HINT_RE = re.compile(
    r"(?i)\b(optional|elective|valbar(?:a)?|valfri(?:a)?|välj|valj|choose|choice|en av|två av|tva av|tre av)\b"
)


@dataclass(frozen=True)
class StandaloneCourse:
    snapshot_date: str
    course_code: str
    course_name_sv: str
    level: str
    catalog_url: str
    institution_name: str


@dataclass(frozen=True)
class CatalogProgram:
    snapshot_date: str
    program_code: str
    program_name_sv: str
    level: str
    catalog_url: str
    institution_name: str


@dataclass(frozen=True)
class ProgramCourseEntry:
    snapshot_date: str
    program_code: str
    program_name_sv: str
    term_label: str
    group_type: str
    group_label: str
    course_code: str | None
    course_name_sv: str
    course_url: str


@dataclass(frozen=True)
class CatalogSnapshot:
    snapshot_date: str
    standalone_courses: list[StandaloneCourse]
    programs: list[CatalogProgram]
    program_courses: list[ProgramCourseEntry]
    warnings: list[str]


def clean_text(value: str | None) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def clean_course_name(value: str) -> str:
    cleaned = clean_text(value)
    cleaned = re.sub(r"\s+\d+(?:[.,]\d+)?\s*hp\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+,+\s*$", "", cleaned)
    return cleaned.strip()


def fallback_course_code_token(token: str) -> str:
    token = token.strip().upper()
    if not (4 <= len(token) <= 8):
        return ""
    if not token.isalnum():
        return ""
    if not any(char.isalpha() for char in token):
        return ""
    if not any(char.isdigit() for char in token):
        return ""
    return token


def extract_course_code(course_url: str, course_name: str = "") -> str:
    parsed = urlparse(course_url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    candidates: list[str] = []
    for segment in reversed(segments):
        candidates.append(segment)
        candidates.extend([part for part in re.split(r"[-_]", segment) if part])
    if course_name:
        candidates.append(course_name)

    for candidate in candidates:
        match = STRICT_COURSE_CODE_RE.search(candidate.upper())
        if match:
            return match.group(1).upper()

    for candidate in candidates:
        fallback = fallback_course_code_token(candidate)
        if fallback:
            return fallback
    return ""


def infer_group_type(label_text: str) -> str:
    text = clean_text(label_text)
    if not text:
        return "mandatory"
    if OPTIONAL_HINT_RE.search(text):
        return "optional"
    return "mandatory"


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": "TeachersNote IDSV Catalog Extractor/1.0",
            "Accept-Language": "sv,en;q=0.8",
        }
    )
    return session


def fetch_catalog_context(session: requests.Session) -> tuple[str, str]:
    response = session.get(CATALOG_URL, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    html = response.text

    page_match = PAGE_ID_RE.search(html)
    portlet_match = EDU_SEARCH_PORTLET_RE.search(html)
    if not page_match or not portlet_match:
        raise RuntimeError(
            "Could not detect catalog page context (page id / education search portlet id)."
        )
    return page_match.group(1), portlet_match.group(1)


def fetch_search_items(
    session: requests.Session,
    page_id: str,
    portlet_id: str,
    facets: dict[str, list[str]],
) -> list[dict[str, Any]]:
    endpoint = f"{BASE_URL}/appresource/{page_id}/{portlet_id}/search"
    items: list[dict[str, Any]] = []
    page_index = 0

    while True:
        payload = {"query": "", "facets": facets, "p": page_index}
        response = session.post(endpoint, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        page_items = data.get("items", [])
        if not isinstance(page_items, list):
            raise RuntimeError("Unexpected catalog search response: 'items' is not a list.")
        items.extend(page_items)

        num_pages = int(data.get("numPages", 0))
        if page_index >= max(num_pages - 1, 0):
            break
        page_index += 1

    return items


def parse_institution_name(page_html: str) -> str:
    match = INSTITUTION_RE.search(page_html)
    if match:
        return clean_text(match.group(1))

    soup = BeautifulSoup(page_html, "html.parser")
    label = soup.find(string=lambda text: bool(text and "Utbildningsansvarig institution" in text))
    if not label:
        return ""
    container = getattr(getattr(label, "parent", None), "parent", None)
    if not container:
        return ""
    raw = clean_text(container.get_text(" ", strip=True))
    return raw.replace("Utbildningsansvarig institution", "").strip()


def parse_program_course_entries(
    html: str,
    snapshot_date: str,
    program_code: str,
    program_name: str,
    warnings: list[str],
) -> list[ProgramCourseEntry]:
    soup = BeautifulSoup(html, "html.parser")
    overview_link = None
    for link in soup.select("h2 a[aria-controls]"):
        if "Programöversikt" in clean_text(link.get_text(" ", strip=True)):
            overview_link = link
            break
    if not overview_link:
        warnings.append(f"{program_code}: missing Programöversikt section")
        return []

    container = soup.find(id=overview_link.get("aria-controls"))
    if not container:
        warnings.append(f"{program_code}: missing Programöversikt container")
        return []

    rows: list[ProgramCourseEntry] = []
    year_label = ""
    term_label = ""
    group_type = "mandatory"
    group_label = ""
    active = False

    for node in container.descendants:
        tag = getattr(node, "name", None)
        if not tag:
            continue

        if tag in {"h3", "h4", "h5", "h6"}:
            text = clean_text(node.get_text(" ", strip=True))
            if not text:
                continue
            if tag == "h3":
                year_label = text
                active = True
            elif tag == "h4":
                term_label = text
                active = True
            group_label = text
            group_type = infer_group_type(text)
            continue

        if tag == "p" and not node.find("a"):
            text = clean_text(node.get_text(" ", strip=True))
            if (
                active
                and text
                and len(text) <= 140
                and "detaljerad kursinformation" not in text.lower()
                and "kurser och scheman" not in text.lower()
            ):
                group_label = text
                group_type = infer_group_type(text)

        if tag == "a" and active:
            href = clean_text(node.get("href"))
            if not href:
                continue
            course_url = urljoin(BASE_URL, href)
            path = urlparse(course_url).path
            if (
                "/sok-kurser-och-program/" not in path
                and "/utbildning/utbildningskatalog/" not in path
            ):
                continue

            course_name = clean_course_name(node.get_text(" ", strip=True))
            if not course_name or not course_url:
                warnings.append(f"{program_code}: skipped empty course name/url for link '{href}'")
                continue

            course_code = extract_course_code(course_url, course_name)
            if not course_code:
                warnings.append(
                    f"{program_code}: missing course_code for '{course_name}' ({course_url})"
                )
            if not term_label:
                warnings.append(
                    f"{program_code}: missing term_label for '{course_code or course_name}'"
                )

            rows.append(
                ProgramCourseEntry(
                    snapshot_date=snapshot_date,
                    program_code=program_code,
                    program_name_sv=program_name,
                    term_label=term_label,
                    group_type=group_type if group_type in {"mandatory", "optional"} else "mandatory",
                    group_label=group_label or term_label or year_label,
                    course_code=course_code or None,
                    course_name_sv=course_name,
                    course_url=course_url,
                )
            )

    return rows


def collect_catalog_snapshot(
    snapshot_date: str,
    *,
    session: requests.Session | None = None,
) -> CatalogSnapshot:
    warnings: list[str] = []
    own_session = session is None
    session = session or build_session()

    try:
        page_id, portlet_id = fetch_catalog_context(session)
        standalone_items = fetch_search_items(
            session,
            page_id,
            portlet_id,
            facets={
                "organisationId": ["323"],
                "educationTypeId": ["22", "24"],
                "forcedReasonCode": ["0"],
            },
        )
        program_items = fetch_search_items(
            session,
            page_id,
            portlet_id,
            facets={
                "organisationId": ["323"],
                "educationTypeId": ["78"],
            },
        )

        standalone_rows: list[StandaloneCourse] = []
        programs: list[CatalogProgram] = []
        program_rows: list[ProgramCourseEntry] = []

        seen_standalone_codes: set[str] = set()

        for item in standalone_items:
            course_code = clean_text(item.get("educationCode")).upper()
            course_name = clean_text(item.get("name"))
            level = clean_text(item.get("level"))
            course_url = urljoin(BASE_URL, clean_text(item.get("uri")))

            if not course_code or not course_name or not course_url:
                warnings.append(
                    "standalone: skipped row with missing required value "
                    f"(code='{course_code}', name='{course_name}', url='{course_url}')"
                )
                continue
            if course_code in seen_standalone_codes:
                continue

            try:
                course_html = session.get(course_url, timeout=DEFAULT_TIMEOUT).text
            except Exception as exc:
                warnings.append(f"{course_code}: failed to fetch course page ({exc})")
                continue

            institution_name = parse_institution_name(course_html)
            if DSV_INSTITUTION_NAME.lower() not in institution_name.lower():
                warnings.append(
                    f"{course_code}: institution check failed (expected DSV, got '{institution_name}')"
                )
                continue

            seen_standalone_codes.add(course_code)
            standalone_rows.append(
                StandaloneCourse(
                    snapshot_date=snapshot_date,
                    course_code=course_code,
                    course_name_sv=course_name,
                    level=level,
                    catalog_url=course_url,
                    institution_name=institution_name,
                )
            )

        for item in program_items:
            program_code = clean_text(item.get("educationCode")).upper()
            program_name = clean_text(item.get("name"))
            program_level = clean_text(item.get("level"))
            program_url = urljoin(BASE_URL, clean_text(item.get("uri")))

            if not program_code or not program_name or not program_url:
                warnings.append(
                    "program: skipped row with missing required value "
                    f"(code='{program_code}', name='{program_name}', url='{program_url}')"
                )
                continue

            try:
                program_html = session.get(program_url, timeout=DEFAULT_TIMEOUT).text
            except Exception as exc:
                warnings.append(f"{program_code}: failed to fetch program page ({exc})")
                continue

            institution_name = parse_institution_name(program_html) or DSV_INSTITUTION_NAME
            programs.append(
                CatalogProgram(
                    snapshot_date=snapshot_date,
                    program_code=program_code,
                    program_name_sv=program_name,
                    level=program_level,
                    catalog_url=program_url,
                    institution_name=institution_name,
                )
            )

            rows_for_program = parse_program_course_entries(
                program_html,
                snapshot_date,
                program_code,
                program_name,
                warnings,
            )
            for row in rows_for_program:
                if not row.course_name_sv or not row.course_url:
                    warnings.append(
                        f"{program_code}: skipped program-course row with empty name/url "
                        f"({row.course_name_sv!r}, {row.course_url!r})"
                    )
                    continue
                program_rows.append(row)

        standalone_rows.sort(key=lambda row: (row.course_code, row.course_name_sv))
        programs.sort(key=lambda row: row.program_code)
        program_rows.sort(
            key=lambda row: (
                row.program_code,
                row.term_label,
                row.group_type,
                row.group_label,
                row.course_code or "",
                row.course_name_sv,
            )
        )

        return CatalogSnapshot(
            snapshot_date=snapshot_date,
            standalone_courses=standalone_rows,
            programs=programs,
            program_courses=program_rows,
            warnings=warnings,
        )
    finally:
        if own_session:
            session.close()


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_snapshot_files(snapshot: CatalogSnapshot, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_date = snapshot.snapshot_date

    standalone_path = out_dir / f"teachersnote_idsv_standalone_courses_{snapshot_date}.csv"
    program_courses_path = out_dir / f"teachersnote_idsv_program_courses_{snapshot_date}.csv"
    programs_path = out_dir / f"teachersnote_idsv_programs_{snapshot_date}.json"

    _write_csv(
        standalone_path,
        fieldnames=[
            "snapshot_date",
            "course_code",
            "course_name_sv",
            "level",
            "catalog_url",
            "institution_name",
        ],
        rows=[asdict(row) for row in snapshot.standalone_courses],
    )
    _write_csv(
        program_courses_path,
        fieldnames=[
            "snapshot_date",
            "program_code",
            "program_name_sv",
            "term_label",
            "group_type",
            "group_label",
            "course_code",
            "course_name_sv",
            "course_url",
        ],
        rows=[asdict(row) for row in snapshot.program_courses],
    )
    with programs_path.open("w", encoding="utf-8") as handle:
        json.dump([asdict(row) for row in snapshot.programs], handle, ensure_ascii=False, indent=2)

    return {
        "standalone_csv": standalone_path,
        "program_courses_csv": program_courses_path,
        "programs_json": programs_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Stockholm University DSV catalog rows and export CSV files."
    )
    parser.add_argument(
        "--snapshot-date",
        default=date.today().isoformat(),
        help="Snapshot date (YYYY-MM-DD), used in output rows and filenames.",
    )
    parser.add_argument(
        "--out-dir",
        default="out",
        help="Output directory for CSV/JSON files.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Fetch and validate only, do not write output files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot_date = args.snapshot_date

    try:
        snapshot = collect_catalog_snapshot(snapshot_date)
    except Exception as exc:
        print(f"ERROR: catalog collection failed: {exc}", file=sys.stderr)
        return 1

    written_paths: dict[str, Path] = {}
    if not args.no_write:
        out_dir = Path(args.out_dir)
        written_paths = write_snapshot_files(snapshot, out_dir)

    print("IDSV catalog extraction completed")
    print(f"Standalone courses: {len(snapshot.standalone_courses)}")
    print(f"Programs: {len(snapshot.programs)}")
    print(f"Program-course rows: {len(snapshot.program_courses)}")
    if written_paths:
        print(f"Standalone CSV: {written_paths['standalone_csv']}")
        print(f"Program-course CSV: {written_paths['program_courses_csv']}")
        print(f"Programs JSON: {written_paths['programs_json']}")
    if snapshot.warnings:
        print("Warnings:")
        for warning in snapshot.warnings:
            print(f"- {warning}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
