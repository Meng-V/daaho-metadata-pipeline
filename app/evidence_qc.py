import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .derivations import parse_iso_date
from .field_validation import place_tokens as _place_tokens
from .places import canonical_place

MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

STATE_MAP = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}

STATE_ALIASES = {
    "D.C": "DC",
    "D.C.": "DC",
    "DISTRICT OF COLUMBIA": "DC",
    "PENN": "PA",
    "PENNA": "PA",
    "PENNS": "PA",
}

STATE_NAME_TO_CODE = {name.upper(): code for code, name in STATE_MAP.items()}

DATE_MONTH_DAY_YEAR = re.compile(
    r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})\b"
)
DATE_DAY_MONTH_YEAR = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b"
)
DATE_MONTH_YEAR = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{4})\b")
DATE_YEAR_ONLY = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
CITY_STATE_LINE = re.compile(
    r"^([A-Za-z .'\-]+?)(?:\s+\d{1,3})?,\s*([A-Za-z. ]+)$"
)

ADDRESS_PREFIX = re.compile(
    r"^(?:address|addr)\s*(?:(?::|--|[-–—])+)\s*",
    re.IGNORECASE,
)


def extract_header_lines(text: Optional[str], max_lines: int = 40) -> List[str]:
    if not text:
        return []
    lines: List[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if line:
            lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def _month_num(raw: str) -> Optional[int]:
    key = raw.strip().lower().rstrip(".")
    return MONTHS.get(key)


def _as_iso(year: int, month: Optional[int], day: Optional[int]) -> Tuple[str, str]:
    if month is None:
        return "year", f"{year:04d}"
    if day is None:
        return "month", f"{year:04d}-{month:02d}"
    return "day", f"{year:04d}-{month:02d}-{day:02d}"


def find_header_dates(lines: Sequence[str]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines):
        for match in DATE_MONTH_DAY_YEAR.finditer(line):
            month = _month_num(match.group(1))
            if not month:
                continue
            day = int(match.group(2))
            year = int(match.group(3))
            precision, iso_date = _as_iso(year, month, day)
            matches.append(
                {
                    "iso_date": iso_date,
                    "precision": precision,
                    "line_idx": idx,
                    "raw": match.group(0),
                    "confidence": 0.95,
                }
            )
        for match in DATE_DAY_MONTH_YEAR.finditer(line):
            day = int(match.group(1))
            month = _month_num(match.group(2))
            if not month:
                continue
            year = int(match.group(3))
            precision, iso_date = _as_iso(year, month, day)
            matches.append(
                {
                    "iso_date": iso_date,
                    "precision": precision,
                    "line_idx": idx,
                    "raw": match.group(0),
                    "confidence": 0.95,
                }
            )
        for match in DATE_MONTH_YEAR.finditer(line):
            month = _month_num(match.group(1))
            if not month:
                continue
            year = int(match.group(2))
            precision, iso_date = _as_iso(year, month, None)
            matches.append(
                {
                    "iso_date": iso_date,
                    "precision": precision,
                    "line_idx": idx,
                    "raw": match.group(0),
                    "confidence": 0.8,
                }
            )
        if len(line) <= 12:
            for match in DATE_YEAR_ONLY.finditer(line):
                year = int(match.group(1))
                precision, iso_date = _as_iso(year, None, None)
                matches.append(
                    {
                        "iso_date": iso_date,
                        "precision": precision,
                        "line_idx": idx,
                        "raw": match.group(0),
                        "confidence": 0.6,
                    }
                )

    dedup: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for match in matches:
        key = (match["iso_date"], match["line_idx"])
        if key not in dedup or match["confidence"] > dedup[key]["confidence"]:
            dedup[key] = match
    return sorted(dedup.values(), key=lambda x: (x["line_idx"], -x["confidence"]))


def _normalize_state(raw_state: str) -> Optional[str]:
    cleaned = raw_state.strip().replace(",", "")
    cleaned = cleaned.rstrip(".")
    cleaned = " ".join(cleaned.split())
    upper = cleaned.upper()
    if upper in STATE_ALIASES:
        upper = STATE_ALIASES[upper]
    if upper in STATE_MAP:
        return STATE_MAP[upper]
    if upper in STATE_NAME_TO_CODE:
        return STATE_MAP[STATE_NAME_TO_CODE[upper]]
    return None


def _normalize_city(raw_city: str) -> str:
    city = raw_city.strip()
    city = ADDRESS_PREFIX.sub("", city).strip()
    city = re.sub(r"\s+\d{1,3}$", "", city)
    city = city.strip(" .,")
    city = " ".join(city.split())

    letters_only = re.sub(r"[^A-Za-z]+", "", city)
    if len(letters_only) > 3 and (city == city.upper() or city == city.lower()):
        city = city.title()

    return city


def find_header_places(lines: Sequence[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen: set = set()
    for idx, line in enumerate(lines):
        compact = " ".join(line.split())
        if "--" in compact:
            token = compact.split(";")[0].strip().strip(",.")
            if "--" in token:
                state, city = token.split("--", 1)
                state_name = _normalize_state(state)
                city_name = _normalize_city(city)
                if state_name and city_name:
                    fast_place = canonical_place(f"{state_name}--{city_name}")
                    key = (fast_place, idx)
                    if key not in seen:
                        seen.add(key)
                        results.append(
                            {
                                "fast_place": fast_place,
                                "line_idx": idx,
                                "raw": compact,
                                "confidence": 0.9,
                            }
                        )

        match = CITY_STATE_LINE.match(compact.strip(" ."))
        if not match:
            continue

        city = _normalize_city(match.group(1))
        state = _normalize_state(match.group(2))
        if not city or not state:
            continue
        fast_place = canonical_place(f"{state}--{city}")
        key = (fast_place, idx)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "fast_place": fast_place,
                "line_idx": idx,
                "raw": compact,
                "confidence": 0.85,
            }
        )
    return sorted(results, key=lambda x: (x["line_idx"], -x["confidence"]))


def _issue(field: str, code: str, message: str, value: Any = None, evidence: Any = None) -> Dict[str, Any]:
    issue: Dict[str, Any] = {"field": field, "code": code, "message": message}
    if value is not None:
        issue["value"] = value
    if evidence is not None:
        issue["evidence"] = evidence
    return issue


def _precision_rank(precision: Optional[str]) -> int:
    if precision == "day":
        return 3
    if precision == "month":
        return 2
    if precision == "year":
        return 1
    return 0


def run_evidence_qc(md: Dict[str, Any], transcript: Optional[str]) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    lines = extract_header_lines(transcript, max_lines=40)
    date_hits = find_header_dates(lines)
    place_hits = find_header_places(lines)

    date_value = md.get("date")
    date_precision = None
    date_valid = True
    try:
        date_precision, _, _, _ = parse_iso_date(date_value)
    except ValueError:
        date_valid = False

    best_date = next((hit for hit in date_hits if hit["confidence"] >= 0.85), None)
    if best_date and (not date_valid or date_precision is None):
        errors.append(
            _issue(
                "date",
                "evidence_date_present_missing_date",
                "Header contains a clear date but metadata date is missing or invalid.",
                value=date_value,
                evidence=best_date,
            )
        )
    elif best_date and date_valid:
        best_precision = best_date.get("precision")
        if _precision_rank(best_precision) > _precision_rank(date_precision):
            warnings.append(
                _issue(
                    "date",
                    "date_precision_mismatch",
                    "Header indicates a more precise date than metadata date.",
                    value=date_value,
                    evidence=best_date,
                )
            )

    place_tokens = _place_tokens(md.get("place"))
    place_value = "; ".join(place_tokens)
    distinct_places = []
    for hit in place_hits:
        fp = hit["fast_place"]
        if fp not in distinct_places:
            distinct_places.append(fp)

    sender_hit = place_hits[0] if place_hits else None
    recipient_place = distinct_places[1] if len(distinct_places) > 1 else None

    if sender_hit and not place_tokens:
        errors.append(
            _issue(
                "place",
                "evidence_place_present_missing_place",
                "Header contains a probable sender/creation place but metadata place is missing.",
                value=place_value,
                evidence=sender_hit,
            )
        )
    elif sender_hit and place_tokens:
        sender_place = sender_hit["fast_place"]
        if sender_place not in place_tokens:
            if recipient_place and recipient_place in place_tokens:
                warnings.append(
                    _issue(
                        "place",
                        "place_looks_like_recipient_not_sender",
                        "Metadata place appears to match recipient location, not sender/creation location.",
                        value=place_value,
                        evidence={"sender": sender_hit, "recipient_fast_place": recipient_place},
                    )
                )
            else:
                warnings.append(
                    _issue(
                        "place",
                        "place_mismatch_with_header_sender",
                        "Metadata place does not match the probable sender/creation place in header.",
                        value=place_value,
                        evidence=sender_hit,
                    )
                )

    if len(distinct_places) >= 2 and len(place_tokens) == 1:
        warnings.append(
            _issue(
                "place",
                "likely_missing_secondary_place",
                "Header suggests both sender and recipient places; metadata includes only one token.",
                value=place_value,
                evidence={"header_places": distinct_places[:2]},
            )
        )

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "signals": {"header_dates": date_hits, "header_places": place_hits},
    }
