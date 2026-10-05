"""Post-extraction checks on the free-text fields that downstream systems parse as structured data.

Structured outputs guarantee the SHAPE of the model's answer, not its content. On the 128-item batch
the model wrote its own reasoning into a contributors entry ("Iso, J. Yun H. T., I. S. O.? No. Need
exact. Wait."), emitted several people as one array element joined by quote characters, and packed
two people into one string with no separator a parser could trust. Each of those reached the
portfolio importer as a name. See docs/DECISIONS.md D-014.

Rule: a person-name field holds exactly one name per element. Anything else is removed from the
field and recorded by value and reason in context, so a reviewer sees it and a rebuild can re-judge
it -- never silently repaired. Splitting "A, B','C, D" into two names is usually right, but the
string came from an output that had already broken down, so it is offered as a suggestion only.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

NAME_FIELDS = ("creator", "contributors", "correspondents")

# Several names in one element, separated by quote-comma-quote: "A, B`,`C, D" or "A, B','C, D".
_JOINED = re.compile(r"""\s*[`'"]\s*,\s*[`'"]\s*""")
# A backtick has no place in a name; it is a fragment of a code-quoted list. Apostrophes are
# deliberately not included (O'Brien, D'Angelo).
_STRAY_QUOTE = re.compile(r"`")
# Model reasoning. "?" is the model querying itself ("Maria Elisabetta?"); the transcription policy's
# own uncertainty markers are [unclear] and [illegible], which are allowed. Words are matched whole,
# so a surname such as "Waite" is unaffected; a person actually surnamed "Wait" would be rejected
# into review rather than lost.
_REASONING = re.compile(
    r"\?"
    r"|\b(?:wait|need exact|hmm+|let me|actually|not sure|i think|double[- ]check|unsure)\b"
    r"|(?:^|\s)no\.(?:\s|$)",
    re.IGNORECASE,
)
# Name suffixes and life dates that legitimately add a second comma: "King, Martin Luther, Jr.",
# "Upham, Alfred H., 1877-1945".
_TRAILING_QUALIFIER = re.compile(
    r",\s*(?:jr\.?|sr\.?|[ivx]{1,4}|esq\.?|ph\.\s?d\.?|m\.\s?d\.?|\d{4}-(?:\d{4})?)\s*$",
    re.IGNORECASE,
)
_MAX_NAME_CHARS = 120


def name_problem(value: str) -> Optional[str]:
    """Why `value` is not exactly one name, or None if it is acceptable."""
    text = value.strip()
    if not text:
        return "empty"
    if _JOINED.search(text):
        return "several names joined by quote characters"
    if _REASONING.search(text):
        return "model reasoning leaked into the field"
    if _STRAY_QUOTE.search(text):
        return "stray quote character"
    if ";" in text:
        return "several names separated by a semicolon"
    if len(text) > _MAX_NAME_CHARS:
        return "too long to be one name"
    if _TRAILING_QUALIFIER.sub("", text).count(",") > 1:
        return "more than one comma: possibly several people in one string"
    return None


def split_joined(value: str) -> List[str]:
    """Undo quote-joining, for a reviewer's convenience only. Never written to a name field."""
    parts = [part.strip(" `'\"") for part in _JOINED.split(value)]
    return [part for part in parts if part]


def validate_name_fields(md: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Remove every name-field value that is not exactly one name. Returns {field: [rejections]}.

    A rejected creator becomes None. A list field keeps its surviving entries in order and becomes
    None if nothing survives, matching how the model reports an absent field.
    """
    rejected: Dict[str, List[Dict[str, Any]]] = {}
    for field in NAME_FIELDS:
        value = md.get(field)
        values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
        kept: List[str] = []
        for raw in values:
            text = str(raw).strip() if raw is not None else ""
            if not text:
                continue
            problem = name_problem(text)
            if problem is None:
                kept.append(text)
                continue
            entry: Dict[str, Any] = {"value": text, "reason": problem}
            parts = split_joined(text)
            if len(parts) > 1:
                entry["suggested_split"] = parts
            rejected.setdefault(field, []).append(entry)
        if field not in rejected:
            continue
        if isinstance(value, list):
            md[field] = kept or None
        else:
            md[field] = kept[0] if kept else None
    return rejected


def name_rejection_notes(rejected: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    notes: List[str] = []
    for field in NAME_FIELDS:
        entries = rejected.get(field)
        if not entries:
            continue
        described = []
        for entry in entries:
            text = f'"{entry["value"]}" ({entry["reason"]}'
            if entry.get("suggested_split"):
                text += "; possible split: " + " | ".join(entry["suggested_split"])
            described.append(text + ")")
        notes.append(
            f"NEEDS NAME REVIEW: removed {field} values that are not exactly one name: "
            + "; ".join(described)
        )
    return notes


def reoffer_rejected_names(md: Dict[str, Any], previous: Any) -> None:
    """Put names a previous build rejected back on their fields, so the current rules re-judge them.

    Name rejections are stored structurally in context rather than parsed back out of the note,
    because the rejected strings are by definition the ones that contain separators.
    """
    if not isinstance(previous, dict):
        return
    for field in NAME_FIELDS:
        values = [e.get("value") for e in previous.get(field) or [] if isinstance(e, dict) and e.get("value")]
        if not values:
            continue
        current = md.get(field)
        if field == "creator":
            if current in (None, ""):
                md[field] = values[0]
            continue
        current = list(current) if isinstance(current, list) else []
        md[field] = current + [v for v in values if v not in current]


_TYPE_NOTE = re.compile(r"^Dropped model-supplied type '(.*)'; genre carries")


def reoffer_dropped_type(md: Dict[str, Any], previous_notes: List[str]) -> None:
    """Restore a type a previous build dropped, so the drop -- and its note -- is reproduced."""
    if md.get("type") not in (None, ""):
        return
    for note in previous_notes:
        match = _TYPE_NOTE.match(note)
        if match:
            md["type"] = match.group(1)
            return


def drop_type(md: Dict[str, Any]) -> List[str]:
    """`type` is never written from model output.

    The model filled it on 10 of 128 items with four spellings of two ideas ("Text", "text",
    "memorandum", "correspondence"); the latter are genres, which `genre` already carries against
    AAT. The April 2026 upload sheet leaves Type blank on every row. See docs/DECISIONS.md D-014.
    """
    value = md.get("type")
    if value in (None, ""):
        return []
    md["type"] = None
    return [f"Dropped model-supplied type '{value}'; genre carries the document type (D-014)."]


def place_tokens(value: Any) -> List[str]:
    """Place as a list of tokens, whichever shape it was stored in.

    `place` is an array from schema v3 on; records written before that (including the committed
    baselines in out/) hold one semicolon-joined string. Every reader goes through this.
    """
    if value is None:
        return []
    items = value if isinstance(value, list) else str(value).split(";")
    return [" ".join(str(item).split()) for item in items if str(item).strip()]


def summarize(md: Dict[str, Any], approved_places: Optional[set] = None) -> Dict[str, Any]:
    """Read-only defect counts for one stored record, without changing it. Used by the audit."""
    counts: Dict[str, Any] = {"name_problems": [], "place_is_string": False,
                              "places_not_approved": [], "type": None}
    for field in NAME_FIELDS:
        value = md.get(field)
        for raw in value if isinstance(value, list) else [value] if value else []:
            problem = name_problem(str(raw))
            if problem:
                counts["name_problems"].append((field, str(raw), problem))
    place = md.get("place")
    counts["place_is_string"] = isinstance(place, str) and bool(place.strip())
    if approved_places is not None:
        counts["places_not_approved"] = [t for t in place_tokens(place) if t not in approved_places]
    counts["type"] = md.get("type") or None
    return counts
