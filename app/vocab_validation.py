import os
import time
from typing import Any, Dict, List, Optional

import requests

FAST_SUGGEST_URL = "https://fast.oclc.org/searchfast/fastsuggest"
GETTY_SPARQL_URL = "https://vocab.getty.edu/sparql.json"

_CACHE: Dict[str, Dict[str, Any]] = {}


def _now() -> float:
    return time.time()


def _cache_ttl() -> int:
    try:
        return int(os.getenv("VOCAB_CACHE_TTL", "86400"))
    except ValueError:
        return 86400


def _api_timeout() -> int:
    try:
        return int(os.getenv("VOCAB_API_TIMEOUT", "5"))
    except ValueError:
        return 5


def _normalize_term(term: str) -> str:
    return " ".join(term.strip().lower().split())


def _get_cache(key: str) -> Optional[Dict[str, Any]]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    if entry["expires_at"] < _now():
        _CACHE.pop(key, None)
        return None
    return entry["value"]


def _set_cache(key: str, value: Dict[str, Any]) -> None:
    _CACHE[key] = {"expires_at": _now() + _cache_ttl(), "value": value}


def _build_fast_result(
    term: str,
    valid: bool,
    suggestions: List[str],
    exact_match: bool,
    cached: bool,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    result = {
        "term": term,
        "valid": valid,
        "suggestions": suggestions,
        "exact_match": exact_match,
        "cached": cached,
        "source": "fast",
    }
    if error:
        result["error"] = error
    return result


def _build_aat_result(
    term: str,
    valid: bool,
    suggestions: List[str],
    exact_match: bool,
    cached: bool,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    result = {
        "term": term,
        "valid": valid,
        "suggestions": suggestions,
        "exact_match": exact_match,
        "cached": cached,
        "source": "aat",
    }
    if error:
        result["error"] = error
    return result


def validate_fast_subject(term: str) -> Dict[str, Any]:
    term = term or ""
    normalized = _normalize_term(term)
    if not normalized:
        return _build_fast_result(term, False, [], False, cached=False, error="Empty term.")

    cache_key = f"fast:{normalized}"
    cached = _get_cache(cache_key)
    if cached:
        cached["cached"] = True
        return cached

    try:
        resp = requests.get(
            FAST_SUGGEST_URL,
            params={"query": term, "queryReturn": "suggestall,idroot,auth", "rows": 10},
            timeout=_api_timeout(),
        )
        resp.raise_for_status()
        payload: Dict[str, Any] = {}
        if resp.content:
            try:
                payload = resp.json()
            except ValueError:
                text = (resp.text or "").strip()
                raise ValueError(text or "FAST API returned non-JSON response.")
        items = payload.get("response", {}).get("docs", [])
        suggestions = []
        exact_match = False
        for item in items:
            # Only an entry carrying a FAST id is an authorized heading; a bare label is a
            # see-reference to some other heading and must not validate (D-015).
            has_id = bool(item.get("idroot"))
            labels: List[str] = []
            suggestall = item.get("suggestall")
            if isinstance(suggestall, list):
                labels.extend([str(value) for value in suggestall if str(value).strip()])
            for key in ("auth", "label"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    labels.append(value)
            for label in labels:
                suggestions.append(label)
                if _normalize_term(label) == normalized and has_id:
                    exact_match = True
        unique_suggestions = list(dict.fromkeys(suggestions))[:10]
        result = _build_fast_result(
            term=term,
            valid=exact_match,
            suggestions=unique_suggestions,
            exact_match=exact_match,
            cached=False,
        )
        _set_cache(cache_key, result)
        return result
    except Exception as exc:
        result = _build_fast_result(
            term=term,
            valid=False,
            suggestions=[],
            exact_match=False,
            cached=False,
            error=str(exc),
        )
        _set_cache(cache_key, result)
        return result


def _build_aat_query(term: str) -> str:
    escaped = term.replace('"', '\\"')
    return f"""
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        SELECT ?label WHERE {{
          ?s a skos:Concept ;
             (skos:prefLabel|skos:altLabel) ?label .
          FILTER (langMatches(lang(?label), "en") || lang(?label) = "")
          FILTER (CONTAINS(LCASE(STR(?label)), LCASE("{escaped}")))
        }}
        LIMIT 10
    """


def validate_aat_genre(term: str) -> Dict[str, Any]:
    term = term or ""
    normalized = _normalize_term(term)
    if not normalized:
        return _build_aat_result(term, False, [], False, cached=False, error="Empty term.")

    cache_key = f"aat:{normalized}"
    cached = _get_cache(cache_key)
    if cached:
        cached["cached"] = True
        return cached

    try:
        query = _build_aat_query(term)
        resp = requests.get(
            GETTY_SPARQL_URL,
            params={"query": query},
            timeout=_api_timeout(),
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        bindings = payload.get("results", {}).get("bindings", [])
        suggestions = []
        exact_match = False
        for binding in bindings:
            label = binding.get("label", {}).get("value", "")
            if not label:
                continue
            suggestions.append(label)
            if _normalize_term(label) == normalized:
                exact_match = True
        unique_suggestions = list(dict.fromkeys(suggestions))[:10]
        result = _build_aat_result(
            term=term,
            valid=exact_match,
            suggestions=unique_suggestions,
            exact_match=exact_match,
            cached=False,
        )
        _set_cache(cache_key, result)
        return result
    except Exception as exc:
        result = _build_aat_result(
            term=term,
            valid=False,
            suggestions=[],
            exact_match=False,
            cached=False,
            error=str(exc),
        )
        _set_cache(cache_key, result)
        return result


def validate_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    subjects = metadata.get("subjects") or []
    genre = metadata.get("genre") or []

    subject_results = []
    for term in subjects:
        if isinstance(term, str) and term.strip():
            subject_results.append(validate_fast_subject(term))

    genre_results = []
    for term in genre:
        if isinstance(term, str) and term.strip():
            genre_results.append(validate_aat_genre(term))

    return {
        "subjects": subject_results,
        "genre": genre_results,
    }
