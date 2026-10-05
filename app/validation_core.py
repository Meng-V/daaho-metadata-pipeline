import re
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Sequence, Set

from .derivations import derive_decade, format_title_date_suffix, parse_iso_date
from .field_validation import place_tokens
from .places import canonical_place

PLACE_TOKEN_PATTERN = re.compile(r"^[^;]+--[^;]+$")



def _issue(
    field: str,
    code: str,
    message: str,
    value: Any = None,
    suggestions: Optional[Sequence[str]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    issue: Dict[str, Any] = {"field": field, "code": code, "message": message}
    if value is not None:
        issue["value"] = value
    if suggestions:
        issue["suggestions"] = list(suggestions)
    if evidence:
        issue["evidence"] = evidence
    return issue


def _first_alpha_char(value: str) -> Optional[str]:
    for char in value:
        if char.isalpha():
            return char
    return None


def _case_insensitive_suggestions(token: str, approved_places: Set[str]) -> List[str]:
    normalized = token.strip().lower()
    suggestions = [place for place in approved_places if place.lower() == normalized]
    return sorted(set(suggestions))


def _normalize_subject_token(token: str) -> str:
    return " ".join(token.strip().lower().split())


def _case_insensitive_subject_suggestions(token: str, approved_subjects: Set[str]) -> List[str]:
    normalized = token.strip().lower()
    suggestions = [subject for subject in approved_subjects if subject.lower() == normalized]
    return sorted(set(suggestions))


def _close_subject_suggestions(
    normalized_token: str,
    normalized_subjects: Dict[str, str],
    limit: int = 5,
) -> List[str]:
    close_keys = get_close_matches(normalized_token, sorted(normalized_subjects.keys()), n=limit, cutoff=0.75)
    suggestions: List[str] = []
    for key in close_keys:
        suggestion = normalized_subjects[key]
        if suggestion not in suggestions:
            suggestions.append(suggestion)
    return suggestions


def validate_core(
    md: Dict[str, Any],
    transcript: Optional[str],
    approved_places: Set[str],
    approved_subjects: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    title = (md.get("title") or "").strip()
    if not title:
        errors.append(_issue("title", "missing_required", "Title is required and cannot be empty."))
    else:
        first_alpha = _first_alpha_char(title)
        if first_alpha and first_alpha != first_alpha.upper():
            errors.append(
                _issue(
                    "title",
                    "title_not_sentence_capitalized",
                    "Title must start with an uppercase alphabetic character.",
                    value=title,
                )
            )

    date_value = md.get("date")
    date_is_valid = True
    try:
        parse_iso_date(date_value)
    except ValueError as exc:
        date_is_valid = False
        errors.append(
            _issue(
                "date",
                "invalid_iso_date",
                f"Date must be YYYY, YYYY-MM, YYYY-MM-DD, or null. {exc}",
                value=date_value,
            )
        )

    title_lower = title.lower()
    if title and date_is_valid:
        if date_value in [None, ""]:
            if not title_lower.endswith(", undated"):
                errors.append(
                    _issue(
                        "title",
                        "title_missing_undated_suffix",
                        "When date is null, title must end with ', undated'.",
                        value=title,
                    )
                )
            undated_index = title_lower.find("undated")
            if undated_index >= 0 and not title_lower.endswith(", undated"):
                errors.append(
                    _issue(
                        "title",
                        "undated_outside_suffix",
                        "The word 'undated' may appear only as the title suffix ', undated'.",
                        value=title,
                    )
                )
        else:
            if "undated" in title_lower:
                errors.append(
                    _issue(
                        "title",
                        "undated_with_dated_item",
                        "Title cannot contain 'undated' when date is present.",
                        value=title,
                    )
                )
            expected_suffix = format_title_date_suffix(date_value)
            expected_title_suffix = f", {expected_suffix}"
            if expected_suffix and not title.endswith(expected_title_suffix):
                errors.append(
                    _issue(
                        "title",
                        "title_date_suffix_mismatch",
                        "Title must end with the human-readable date suffix derived from date.",
                        value=title,
                        suggestions=[expected_title_suffix],
                    )
                )

    expected_decade = None
    if date_is_valid:
        expected_decade = derive_decade(date_value)
    decade_value = md.get("decade")
    if expected_decade is None:
        if decade_value not in [None, ""]:
            errors.append(
                _issue(
                    "decade",
                    "decade_should_be_null",
                    "Decade must be null when date is null.",
                    value=decade_value,
                )
            )
    elif decade_value != expected_decade:
        errors.append(
            _issue(
                "decade",
                "decade_mismatch",
                "Decade must match date-derived decade.",
                value=decade_value,
                suggestions=[expected_decade],
            )
        )

    tokens = place_tokens(md.get("place"))
    if tokens:
        for token in tokens:
            # An approved heading is valid whatever its shape: FAST's jurisdiction-level headings,
            # such as "Washington (D.C.)", have no "--" at all. Only unapproved tokens are
            # held to the State--City pattern.
            if token in approved_places or canonical_place(token) in approved_places:
                continue
            if not PLACE_TOKEN_PATTERN.match(token):
                errors.append(
                    _issue(
                        "place",
                        "invalid_place_format",
                        "Location token must use FAST-style 'State--City' format.",
                        value=token,
                    )
                )
                continue

            if approved_places:
                if token not in approved_places:
                    canonical = canonical_place(token)
                    if canonical in approved_places:
                        continue

                    suggestions: List[str] = []
                    if canonical != token and canonical in approved_places:
                        suggestions.append(canonical)
                    suggestions.extend(_case_insensitive_suggestions(token, approved_places))
                    if not suggestions:
                        suggestions = sorted(list(approved_places))[:5]
                    errors.append(
                        _issue(
                            "place",
                            "place_not_in_approved_list",
                            "Location token is not in the locally approved FAST place list.",
                            value=token,
                            suggestions=suggestions[:5],
                        )
                    )

    subjects = md.get("subjects")
    if not isinstance(subjects, list) or len([term for term in subjects if str(term).strip()]) == 0:
        errors.append(
            _issue(
                "subjects",
                "missing_required",
                "Subjects are missing; at least one subject term is required.",
            )
        )
    elif approved_subjects:
        normalized_subjects: Dict[str, str] = {}
        for approved_term in sorted(approved_subjects):
            normalized_approved_term = _normalize_subject_token(approved_term)
            if normalized_approved_term and normalized_approved_term not in normalized_subjects:
                normalized_subjects[normalized_approved_term] = approved_term

        for raw_term in subjects:
            term = str(raw_term).strip()
            if not term:
                continue
            normalized_term = _normalize_subject_token(term)
            if normalized_term not in normalized_subjects:
                suggestions: List[str] = []
                suggestions.extend(_case_insensitive_subject_suggestions(term, approved_subjects))
                for candidate in _close_subject_suggestions(normalized_term, normalized_subjects):
                    if candidate not in suggestions:
                        suggestions.append(candidate)
                    if len(suggestions) >= 5:
                        break
                if not suggestions:
                    suggestions = sorted(approved_subjects)[:5]

                errors.append(
                    _issue(
                        "subjects",
                        "subject_not_in_locally_approved_list",
                        "Subject is not in the locally approved reviewed-subject list.",
                        value=term,
                        suggestions=suggestions[:5] or None,
                    )
                )

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}
