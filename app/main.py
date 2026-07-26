import argparse
import csv
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .ai_metadata import (
    PROMPT_VERSION,
    ExtractionFailed,
    apply_review_overrides,
    apply_tier_policy,
    default_detail,
    extract_metadata,
    transcribe_with_model,
)
from .cost import (
    DEFAULT_TIER,
    TIERS,
    CostLedger,
    free_record,
    record_from_usage,
)
from .derivations import apply_derivations, derive_normalized_title
from .evidence_qc import run_evidence_qc
from .grouping import (
    DEFAULT_MAX_PAGES_PER_CALL,
    chunk_pages,
    group_items,
    page_label,
)
try:
    from .gdrive import pull_files_from_folder
except ImportError:
    pull_files_from_folder = None
from .ocr import (
    image_bytes,
    image_dimensions,
    sent_dimensions,
    tesseract_available,
    tesseract_ocr,
)
from .schema import LOC15_SCHEMA, SCHEMA_VERSION, TIER3_DEFAULTABLE_FIELDS
from .validation_core import validate_core

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

try:
    from jsonschema import Draft7Validator
except Exception:
    Draft7Validator = None


def _merge_chunk_metadata(chunks: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
    """Combine per-chunk metadata for an item too large to send in one request.

    Transcripts concatenate in page order -- the [page N] markers carry the sequence. Descriptive
    scalars come from the FIRST chunk, which holds the cover, title page and letterhead, i.e. the
    pages that actually establish title, date and creator. Scalars the first chunk left null are
    filled from later chunks, since a date can appear on a signature page. List fields union across
    chunks. Confidence is taken as the minimum, because an item is only as trustworthy as its worst
    page.
    """
    notes: List[str] = []
    if not chunks:
        return {}, notes
    if len(chunks) == 1:
        return chunks[0], notes

    merged: Dict[str, Any] = {}
    transcripts = [c.get("transcript") for c in chunks if (c.get("transcript") or "").strip()]

    keys = {k for chunk in chunks for k in chunk}
    for key in keys:
        values = [chunk.get(key) for chunk in chunks]
        if key == "transcript":
            merged[key] = "\n\n".join(t.strip() for t in transcripts) or None
            continue
        if key == "field_confidence":
            scores: Dict[str, Any] = {}
            for value in values:
                for field, score in (value or {}).items():
                    if isinstance(score, int):
                        scores[field] = min(score, scores[field]) if isinstance(scores.get(field), int) else score
                    else:
                        scores.setdefault(field, None)
            merged[key] = scores or None
            continue
        if any(isinstance(v, list) for v in values):
            union: List[Any] = []
            for value in values:
                for entry in (value or []):
                    if entry not in union:
                        union.append(entry)
            merged[key] = union or None
            continue
        # Scalars: first non-null wins, first chunk first.
        merged[key] = next((v for v in values if v not in (None, "")), None)

    notes.append(
        f"Item spanned {len(chunks)} API calls because it exceeds the per-request page limit; "
        f"metadata merged (scalars from the earliest page carrying a value, lists unioned, "
        f"confidence minimized)."
    )
    return merged, notes


class RunManifest:
    """Append-only per-item outcome log, so a 300-image run's status is knowable.

    Without this, the only evidence a run finished was the presence of output files -- which said
    nothing about items that errored, and (before ExtractionFailed) nothing about items whose
    output was written from empty metadata. Thread-safe: a concurrent run appends from workers.
    """

    def __init__(self, path: Optional[str]):
        self.path = Path(path) if path else None
        self.records: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        if self.path:
            os.makedirs(self.path.parent, exist_ok=True)

    def add(self, item_id: str, status: str, **extra: Any) -> None:
        record = {"item_id": item_id, "status": status, **extra}
        with self._lock:
            self.records.append(record)
            if self.path:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def counts(self) -> Dict[str, int]:
        tally: Dict[str, int] = {}
        for record in self.records:
            tally[record["status"]] = tally.get(record["status"], 0) + 1
        return tally

    def failures(self) -> List[Dict[str, Any]]:
        return [r for r in self.records if r["status"] == "failed"]


def _validate(obj: Dict[str, Any]) -> str:
    if Draft7Validator is None:
        return ""
    validator = Draft7Validator(LOC15_SCHEMA)
    errors = sorted(validator.iter_errors(obj), key=lambda err: err.path)
    return "; ".join([f"{'.'.join(map(str, err.path))}: {err.message}" for err in errors])


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def _load_controlled_list(path_str: Optional[str]) -> Set[str]:
    if not path_str:
        return set()
    path = Path(path_str)
    if not path.exists():
        return set()
    values: Set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        # Strip trailing inline comments so vocab files can carry provenance (e.g. AAT ids)
        # beside each term. No controlled term in use contains '#'.
        token = line.split("#", 1)[0].strip()
        if not token:
            continue
        values.add(token)
    return values


def _normalize_item_id(value: str) -> str:
    stem = Path(str(value).strip()).stem
    if stem.endswith(".loc15"):
        stem = stem[: -len(".loc15")]
    if stem.endswith("_Recto"):
        stem = stem[: -len("_Recto")]
    return stem


def _first_header_index(headers: List[str], name: str) -> Optional[int]:
    try:
        return headers.index(name)
    except ValueError:
        return None


def _csv_cell(row: List[str], index: Optional[int]) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _load_summary_examples(path_str: str) -> Dict[str, Dict[str, str]]:
    if not path_str:
        return {}
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Summary examples CSV not found: {path_str}")

    examples: Dict[str, Dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers = next(reader)
        indexes = {
            "identifier": _first_header_index(headers, "Identifier"),
            "title": _first_header_index(headers, "Title"),
            "summary": _first_header_index(headers, "Summary"),
            "creator": _first_header_index(headers, "Creator"),
            "date": _first_header_index(headers, "Date"),
            "location": _first_header_index(headers, "Location"),
            "genre": _first_header_index(headers, "Genre"),
        }
        if indexes["identifier"] is None or indexes["summary"] is None:
            raise ValueError("Summary examples CSV must contain Identifier and Summary columns.")

        for row in reader:
            identifier = _normalize_item_id(_csv_cell(row, indexes["identifier"]))
            summary = _csv_cell(row, indexes["summary"])
            if not identifier or not summary:
                continue
            examples[identifier] = {
                "identifier": identifier,
                "title": _csv_cell(row, indexes["title"]),
                "creator": _csv_cell(row, indexes["creator"]),
                "date": _csv_cell(row, indexes["date"]),
                "location": _csv_cell(row, indexes["location"]),
                "genre": _csv_cell(row, indexes["genre"]),
                "summary": summary,
            }
    return examples


def _format_summary_examples(
    item_id: str,
    examples: Dict[str, Dict[str, str]],
    mode: str,
) -> tuple[str, List[str]]:
    if not examples:
        return "", []
    if mode != "leave-one-out":
        raise ValueError(f"Unsupported summary few-shot mode: {mode}")

    included_ids = [identifier for identifier in sorted(examples) if identifier != item_id]
    blocks: List[str] = [
        "SUMMARY STYLE EXAMPLES",
        "Use these approved human-written Summary examples only to match tone, detail, and structure.",
        "Do not copy facts from these examples into the current item unless they are supported by the current OCR/image.",
        f"The current item id is {item_id}; its own approved Summary is intentionally excluded.",
        "",
    ]
    for identifier in included_ids:
        example = examples[identifier]
        blocks.extend(
            [
                f"Example Identifier: {example['identifier']}",
                f"Title: {example['title'] or '(blank)'}",
                f"Creator: {example['creator'] or '(blank)'}",
                f"Date: {example['date'] or '(blank)'}",
                f"Location: {example['location'] or '(blank)'}",
                f"Genre: {example['genre'] or '(blank)'}",
                f"Approved Summary: {example['summary']}",
                "",
            ]
        )
    return "\n".join(blocks).strip(), included_ids


def _normalize_subject_token(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _derive_subjects_from_metadata(md: Dict[str, Any], normalized_approved_subjects: Dict[str, str]) -> List[str]:
    parts: List[str] = []
    for field in ("title", "generated_title", "description", "transcript", "text_reading"):
        value = md.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    for field in ("keywords", "genre", "theme"):
        values = md.get(field)
        if isinstance(values, list):
            for value in values:
                text = str(value).strip()
                if text:
                    parts.append(text)
    haystack = " ".join(parts).lower()
    if not haystack:
        return []

    scored: List[tuple] = []
    for normalized_term, approved_term in normalized_approved_subjects.items():
        tokens = [token for token in re.findall(r"[a-z0-9]+", normalized_term) if len(token) >= 3]
        if not tokens:
            continue
        if all(token in haystack for token in tokens):
            scored.append((len(tokens), approved_term))
    scored.sort(key=lambda item: (-item[0], item[1]))

    subjects: List[str] = []
    for _, term in scored:
        if term not in subjects:
            subjects.append(term)
        if len(subjects) >= 3:
            break
    return subjects


def _enforce_approved_subjects(md: Dict[str, Any], approved_subjects: Set[str]) -> List[str]:
    if not approved_subjects:
        return []

    notes: List[str] = []
    normalized_approved_subjects: Dict[str, str] = {}
    for approved_term in sorted(approved_subjects):
        normalized_term = _normalize_subject_token(approved_term)
        if normalized_term and normalized_term not in normalized_approved_subjects:
            normalized_approved_subjects[normalized_term] = approved_term

    subjects: List[str] = []
    rejected: List[str] = []
    existing_subjects = md.get("subjects")
    if isinstance(existing_subjects, list):
        for raw_subject in existing_subjects:
            term = str(raw_subject).strip()
            if not term:
                continue
            normalized_term = _normalize_subject_token(term)
            canonical_term = normalized_approved_subjects.get(normalized_term)
            if canonical_term is None:
                matches = get_close_matches(normalized_term, sorted(normalized_approved_subjects.keys()), n=1, cutoff=0.86)
                if matches:
                    canonical_term = normalized_approved_subjects[matches[0]]
            if canonical_term:
                if canonical_term not in subjects:
                    subjects.append(canonical_term)
            else:
                rejected.append(term)

    if not subjects:
        subjects = _derive_subjects_from_metadata(md, normalized_approved_subjects)
        if subjects:
            notes.append("Derived subjects deterministically from metadata text overlap with approved FAST list.")

    # No arbitrary fallback. This previously wrote "Correspondence" -- or, failing that, whichever
    # approved term sorted first alphabetically -- whenever nothing matched. On a 47-term pilot
    # vocabulary that silently stamped an unrelated subject onto any item outside its coverage, and
    # the result carried the same provenance label as a real reading. An empty field a cataloger can
    # see is strictly better than a wrong one they cannot. See docs/DECISIONS.md D-010.
    if rejected:
        notes.append(
            "Rejected subject terms absent from the approved FAST list: "
            + "; ".join(sorted(set(rejected)))
        )
    if not subjects:
        notes.append("NEEDS VOCAB REVIEW: no approved FAST subject matched; left empty rather than guessing.")

    md["subjects"] = subjects
    return notes


def _enforce_approved_genre(md: Dict[str, Any], approved_genre: Set[str]) -> List[str]:
    if not approved_genre:
        return []

    notes: List[str] = []
    normalized_approved_genre: Dict[str, str] = {}
    for approved_term in sorted(approved_genre):
        normalized_term = _normalize_subject_token(approved_term)
        if normalized_term and normalized_term not in normalized_approved_genre:
            normalized_approved_genre[normalized_term] = approved_term

    genre: List[str] = []
    rejected: List[str] = []
    existing_genre = md.get("genre")
    if isinstance(existing_genre, list):
        for raw_genre in existing_genre:
            term = str(raw_genre).strip()
            if not term:
                continue
            normalized_term = _normalize_subject_token(term)
            canonical_term = normalized_approved_genre.get(normalized_term)
            if canonical_term is None:
                matches = get_close_matches(normalized_term, sorted(normalized_approved_genre.keys()), n=1, cutoff=0.86)
                if matches:
                    canonical_term = normalized_approved_genre[matches[0]]
            if canonical_term:
                if canonical_term not in genre:
                    genre.append(canonical_term)
            else:
                rejected.append(term)

    # Same reasoning as subjects: no arbitrary fallback. This previously stamped "correspondence"
    # on anything unmatched, which would mislabel every clipping, form and telegram in a batch whose
    # genre fell outside the vocabulary. See docs/DECISIONS.md D-010.
    if rejected:
        notes.append(
            "Rejected genre terms absent from the approved AAT list: "
            + "; ".join(sorted(set(rejected)))
        )
    if not genre:
        notes.append("NEEDS VOCAB REVIEW: no approved AAT genre matched; left empty rather than guessing.")

    md["genre"] = genre
    return notes


def _enforce_approved_places(md: Dict[str, Any], approved_places: Set[str]) -> List[str]:
    if not approved_places:
        return []

    place_value = md.get("place")
    if not isinstance(place_value, str) or not place_value.strip():
        return []

    notes: List[str] = []
    normalized_places: Dict[str, str] = {place.lower(): place for place in approved_places}
    places: List[str] = []
    rejected: List[str] = []
    for raw_token in place_value.split(";"):
        token = " ".join(raw_token.strip().split())
        if not token:
            continue

        canonical = token if token in approved_places else None
        if canonical is None:
            lower_token = token.lower()
            canonical = normalized_places.get(lower_token)
            if canonical is None and "washington" in lower_token and ("d.c" in lower_token or "district of columbia" in lower_token):
                dc_place = "District of Columbia--Washington"
                if dc_place in approved_places:
                    canonical = dc_place

        if canonical:
            if canonical not in places:
                places.append(canonical)
                if canonical != token:
                    notes.append(f"Canonicalized place '{token}' to '{canonical}'.")
        else:
            rejected.append(token)

    # Dropped tokens used to vanish without a trace: a two-token place where only one matched was
    # silently rewritten to the single match. With a 9-entry pilot place list that loses real data
    # invisibly, so every rejection is now recorded. Note the asymmetry, which is deliberate: when
    # NO token matches, the original value is left intact rather than blanked, because an
    # unvalidated place a cataloger can see beats an empty field.
    if rejected:
        notes.append(
            "Place tokens absent from the approved FAST list: " + "; ".join(sorted(set(rejected)))
        )
    if places and "; ".join(places) != place_value:
        md["place"] = "; ".join(places)
    elif not places:
        notes.append(
            "NEEDS VOCAB REVIEW: no approved FAST place matched; original value kept unvalidated."
        )
    return notes


def _build_online_vocab_advisory(md: Dict[str, Any]) -> Dict[str, Any]:
    from .vocab_validation import validate_metadata

    payload = validate_metadata(md)
    warnings: List[Dict[str, Any]] = []
    for field in ("subjects", "genre"):
        for result in payload.get(field, []):
            if result.get("valid") is True and not result.get("error"):
                continue
            warning: Dict[str, Any] = {
                "field": field,
                "term": result.get("term"),
                "message": "Online vocabulary advisory indicates no exact authority match.",
            }
            if result.get("error"):
                warning["message"] = f"Online vocabulary advisory failed: {result.get('error')}"
            suggestions = result.get("suggestions") or []
            if suggestions:
                warning["suggestions"] = suggestions[:5]
            warnings.append(warning)
    return {"warnings": warnings}


def _apply_validation(
    md: Dict[str, Any],
    transcript: Optional[str],
    approved_places: Set[str],
    approved_subjects: Set[str],
    online_vocab_advisory: bool,
) -> Dict[str, Any]:
    context_updates: Dict[str, Any] = {
        "validation_core": validate_core(
            md=md,
            transcript=transcript,
            approved_places=approved_places,
            approved_subjects=approved_subjects or None,
        ),
        "validation_evidence_qc": run_evidence_qc(md=md, transcript=transcript),
    }
    if online_vocab_advisory:
        context_updates["validation_online"] = _build_online_vocab_advisory(md)
    return context_updates


def _normalized_title_validation(
    md: Dict[str, Any],
    normalized_title: Optional[str],
    approved_places: Set[str],
    approved_subjects: Set[str],
) -> Dict[str, Any]:
    if not normalized_title:
        return {"title_ok": False, "title_error_codes": ["normalized_title_missing"]}
    test_md = dict(md)
    test_md["title"] = normalized_title
    report = validate_core(
        md=test_md,
        transcript=test_md.get("transcript") or test_md.get("text_reading"),
        approved_places=approved_places,
        approved_subjects=approved_subjects or None,
    )
    title_errors = [entry for entry in report.get("errors", []) if entry.get("field") == "title"]
    return {
        "title_ok": len(title_errors) == 0,
        "title_error_codes": [entry.get("code") for entry in title_errors],
    }


def _policy_defaults(
    defaults: Dict[str, Any],
    collection: str,
    repository: str,
    permalink: str,
) -> Dict[str, Any]:
    merged = dict(defaults)
    if collection:
        merged["collection"] = collection
    if repository:
        merged["repository"] = repository
    if permalink:
        merged["permalink"] = permalink
    return merged


_REJECTION_NOTES = {
    "subjects": "Rejected subject terms absent from the approved FAST list:",
    "genre": "Rejected genre terms absent from the approved AAT list:",
}


def _reoffer_rejected_terms(md: Dict[str, Any], previous_notes: List[str]) -> Dict[str, List[str]]:
    """Put previously rejected terms back on the list field so enforcement can re-judge them.

    Returns {field: [terms re-offered]}. Order matters: surviving terms stay first, so if the
    vocabulary still rejects the re-offered ones nothing changes.
    """
    restored: Dict[str, List[str]] = {}
    for field, prefix in _REJECTION_NOTES.items():
        terms: List[str] = []
        for note in previous_notes:
            if not note.startswith(prefix):
                continue
            for term in note[len(prefix):].split(";"):
                term = term.strip()
                if term and term not in terms:
                    terms.append(term)
        if not terms:
            continue
        current = md.get(field)
        current = list(current) if isinstance(current, list) else []
        fresh = [t for t in terms if t not in current]
        if fresh:
            md[field] = current + fresh
            restored[field] = fresh
    return restored


def rebuild_existing_outputs(
    out_dir: str,
    defaults: Dict[str, Any],
    apply_reviews: bool,
    approved_places: Set[str],
    approved_subjects: Set[str],
    approved_genre: Set[str],
    online_vocab_advisory: bool,
) -> None:
    out_path = Path(out_dir)
    if not out_path.exists():
        print(f"No output directory found: {out_dir}")
        return

    for json_file in sorted(out_path.glob("*.loc15.json")):
        try:
            raw = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"x {json_file.name}: {exc}")
            continue

        md = raw.get("metadata", raw)
        context = raw.get("context", {})

        # Re-offer terms a previous run rejected. Enforcement removes out-of-vocabulary terms from
        # the metadata, so after a vocabulary expansion a plain rebuild could only recover values
        # still present -- it could not restore what the model originally proposed. D-010 records
        # every rejection by name in policy_notes precisely so nothing is lost; this reads them
        # back and lets the current vocabulary judge them again.
        restored = _reoffer_rejected_terms(md, context.get("policy_notes") or [])

        review_notes: List[str] = []
        if apply_reviews:
            review_path = out_path / f"{json_file.stem.replace('.loc15', '')}.review.json"
            if review_path.exists():
                try:
                    review_data = json.loads(review_path.read_text(encoding="utf-8"))
                    md, review_notes = apply_review_overrides(md, review_data)
                except Exception:
                    review_notes.append("Failed to apply review overrides.")

        md, derivation_notes = apply_derivations(md)
        raw_title = md.get("title")
        normalized_title, title_notes, title_changed = derive_normalized_title(raw_title, md.get("date"))
        if title_changed and normalized_title:
            md["title"] = normalized_title

        # Tier 3 holds archival placement (box, folder, identifier, repository ...). The tier policy
        # clears any Tier 3 field for which no explicit default is supplied, which is right for a
        # fresh extraction -- it must never be inferred -- but destructive on a rebuild: values
        # already recorded would be silently wiped unless every flag were re-passed. Carry existing
        # values forward, and let an explicit CLI default override them.
        rebuild_defaults = dict(defaults)
        preserved: List[str] = []
        for field in TIER3_DEFAULTABLE_FIELDS:
            if rebuild_defaults.get(field) in (None, ""):
                existing = md.get(field)
                if existing not in (None, "", [], {}):
                    rebuild_defaults[field] = existing
                    preserved.append(field)

        md, metadata_tiers, field_provenance, policy_notes = apply_tier_policy(md, defaults=rebuild_defaults)
        if preserved:
            policy_notes = policy_notes + [
                "Preserved existing Tier 3 values on rebuild: " + ", ".join(sorted(preserved))
            ]
        if restored:
            policy_notes = policy_notes + [
                "Re-offered previously rejected terms to the current vocabulary: "
                + "; ".join(f"{field}={', '.join(terms)}" for field, terms in sorted(restored.items()))
            ]
        subject_notes = _enforce_approved_subjects(md, approved_subjects)
        if subject_notes:
            policy_notes = policy_notes + subject_notes
        genre_notes = _enforce_approved_genre(md, approved_genre)
        if genre_notes:
            policy_notes = policy_notes + genre_notes
        place_notes = _enforce_approved_places(md, approved_places)
        if place_notes:
            policy_notes = policy_notes + place_notes

        context.update(
            _apply_validation(
                md=md,
                transcript=md.get("transcript") or md.get("text_reading"),
                approved_places=approved_places,
                approved_subjects=approved_subjects,
                online_vocab_advisory=online_vocab_advisory,
            )
        )
        context["title_derivation"] = {
            "raw_title": raw_title,
            "normalized_title": normalized_title,
            "applied": bool(title_changed),
            "normalized_title_validation": _normalized_title_validation(
                md=md,
                normalized_title=normalized_title,
                approved_places=approved_places,
                approved_subjects=approved_subjects,
            ),
        }

        if derivation_notes:
            context["derivation_notes"] = derivation_notes
        if title_notes:
            context["title_derivation"]["notes"] = title_notes
        if policy_notes or review_notes:
            context["policy_notes"] = policy_notes + review_notes
        context["schema_version"] = SCHEMA_VERSION
        context["rebuilt_from_existing"] = True

        envelope = {
            "metadata": md,
            "metadata_tiers": metadata_tiers,
            "field_provenance": field_provenance,
            "context": context,
        }
        validation_error = _validate(md)
        if validation_error:
            envelope["context"]["validation_error"] = validation_error
        json_file.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Rebuilt {json_file.name}")


def process_item(
    paths: List[str],
    out_dir: str,
    collection: str,
    repository: str,
    permalink: str,
    model: str,
    approved_places: Set[str],
    approved_subjects: Set[str],
    approved_genre: Set[str],
    online_vocab_advisory: bool,
    output_ext: str = ".loc15.json",
    defaults: Optional[Dict[str, Any]] = None,
    overwrite: bool = False,
    apply_reviews: bool = False,
    prompt_version: str = PROMPT_VERSION,
    summary_examples: Optional[Dict[str, Dict[str, str]]] = None,
    summary_fewshot_mode: str = "leave-one-out",
    ledger: Optional[CostLedger] = None,
    reasoning_effort: str = "",
    ocr_fallback: bool = True,
    manifest: Optional[RunManifest] = None,
    item_id: str = "",
    max_pages_per_call: int = DEFAULT_MAX_PAGES_PER_CALL,
) -> str:
    """Produce ONE metadata record from all images of ONE archival item.

    `paths` is the item's pages in reading order. A single-file item is just the one-element case.
    Items larger than max_pages_per_call are split across requests and merged, because sending 36
    pages at ~15,000 image tokens each would cross into long-context pricing and cost more than
    processing them separately.

    Returns a status: ok | skipped | missing | failed. On failure NOTHING is written to
    output_path, so a resume retries the item instead of skipping a hole; a sibling .failed.json
    records the reason.
    """
    page_paths = [Path(p) for p in paths]
    present = [p for p in page_paths if p.exists()]
    item_id = item_id or (_normalize_item_id(page_paths[0].name) if page_paths else "")
    if not present:
        print(f"Skip missing: {', '.join(str(p) for p in page_paths) or '(no paths)'}")
        if manifest:
            manifest.add(item_id, "missing", paths=[str(p) for p in page_paths])
        return "missing"
    missing_pages = [p.name for p in page_paths if not p.exists()]

    output_path = Path(out_dir) / f"{item_id}{output_ext}"
    label = item_id if len(present) == 1 else f"{item_id} ({len(present)} pages)"
    # Runs before item grouping named their output after the FILE stem, so a single-page item
    # landed at e.g. BC-0692_Recto.loc15.json rather than BC-0692.loc15.json. Honor the legacy name
    # when deciding whether work is already done, or a resume would re-bill the whole pilot set.
    existing = [output_path] + [
        Path(out_dir) / f"{page.stem}{output_ext}" for page in present if page.stem != item_id
    ]
    already = next((p for p in existing if p.exists()), None)
    if already and not overwrite:
        suffix = "" if already == output_path else f" [legacy name {already.name}]"
        print(f"Skipping {label} (already processed){suffix}")
        if manifest:
            manifest.add(item_id, "skipped", output=already.name)
        return "skipped"

    print(f"Processing {label}...", end="", flush=True)
    summary_style_examples, summary_example_ids = _format_summary_examples(
        item_id=item_id,
        examples=summary_examples or {},
        mode=summary_fewshot_mode,
    )
    detail = default_detail(model)

    # Local OCR across every page, concatenated. Free, and a no-op when pytesseract is absent.
    ocr_parts, confidences = [], []
    for page in present:
        page_text, page_conf = tesseract_ocr(str(page))
        if page_text.strip():
            ocr_parts.append(page_text)
        confidences.append(page_conf)
    text = "\n\n".join(ocr_parts)
    conf = max(confidences) if confidences else 0.0
    if ledger:
        # Record honestly whether local OCR actually ran. pytesseract being absent silently turns
        # tesseract_ocr() into a no-op, which is what made the billable fallback fire on every
        # item in the first full run -- see docs/DECISIONS.md D-009b.
        if tesseract_available():
            note = f"local OCR over {len(present)} page(s), no API cost ({len(text.strip())} chars)"
        else:
            note = "SKIPPED: pytesseract not installed, so local OCR did not run"
        ledger.add(free_record(item_id, "tesseract", note=note))

    images = [image_bytes(str(page)) for page in present]
    labels = [page_label(page) for page in present]

    if ocr_fallback and len(text.strip()) < 25:
        try:
            model_text, ocr_usage = transcribe_with_model(
                images[0][0], model=model, mime=images[0][1], detail=detail,
                reasoning_effort=reasoning_effort,
            )
            if ledger:
                ledger.add(record_from_usage(
                    item_id, "ocr_fallback", model, ocr_usage,
                    prompt_version=prompt_version, detail=detail,
                    note="Tesseract returned under 25 chars (first page only)",
                ))
            if len(model_text) > len(text):
                text = model_text
                conf = max(conf, 85.0)
        except Exception:
            pass

    page_chunks = chunk_pages(present, max_pages_per_call)
    index_chunks = chunk_pages(list(range(len(present))), max_pages_per_call)
    usage_sink: List[Any] = []
    chunk_results: List[Dict[str, Any]] = []
    try:
        for chunk_no, indexes in enumerate(index_chunks, start=1):
            chunk_images = [images[i] for i in indexes]
            chunk_labels = [labels[i] for i in indexes]
            chunk_results.append(extract_metadata(
                chunk_images,
                text if chunk_no == 1 else "",
                filename=present[indexes[0]].name,
                model=model,
                known_collection=collection,
                known_repository=repository,
                known_permalink=permalink,
                prompt_version=prompt_version,
                summary_style_examples=summary_style_examples,
                detail=detail,
                reasoning_effort=reasoning_effort,
                usage_sink=usage_sink,
                page_labels=chunk_labels,
            ))
    except ExtractionFailed as exc:
        # Bill what was actually spent, then write NO output. The item stays unprocessed so a
        # resume retries it rather than skipping a silently-empty record.
        if ledger:
            for index, usage in enumerate(usage_sink):
                ledger.add(record_from_usage(
                    item_id, "extraction", model, usage,
                    prompt_version=prompt_version, detail=detail,
                    note="failed attempt" if index else "failed",
                ))
        spent = ledger.total_for(item_id) if ledger else 0.0
        os.makedirs(out_dir, exist_ok=True)
        (Path(out_dir) / f"{item_id}.failed.json").write_text(
            json.dumps({
                "item_id": item_id,
                "pages": [p.name for p in present],
                "chunks_completed": len(chunk_results),
                "chunks_total": len(index_chunks),
                "error": str(exc),
                "model": model,
                "prompt_version": prompt_version,
                "attempts_billed": len(usage_sink),
                "cost_usd": round(spent, 6),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f" FAILED (${spent:.4f}): {exc}")
        if manifest:
            manifest.add(item_id, "failed", error=str(exc), cost_usd=round(spent, 6),
                         pages=len(present))
        return "failed"

    if ledger:
        for index, usage in enumerate(usage_sink):
            ledger.add(record_from_usage(
                item_id, "extraction", model, usage,
                prompt_version=prompt_version, detail=detail,
                note=f"chunk {index + 1}/{len(index_chunks)}" if len(index_chunks) > 1 else "",
            ))

    md, merge_notes = _merge_chunk_metadata(chunk_results)

    review_notes: List[str] = []
    if apply_reviews:
        review_path = Path(out_dir) / f"{item_id}.review.json"
        if review_path.exists():
            try:
                review_data = json.loads(review_path.read_text(encoding="utf-8"))
                md, review_notes = apply_review_overrides(md, review_data)
            except Exception:
                review_notes.append("Failed to apply review overrides.")
    if merge_notes:
        review_notes = merge_notes + review_notes

    md, derivation_notes = apply_derivations(md)
    raw_title = md.get("title")
    normalized_title, title_notes, title_changed = derive_normalized_title(raw_title, md.get("date"))
    if title_changed and normalized_title:
        md["title"] = normalized_title
    md, metadata_tiers, field_provenance, policy_notes = apply_tier_policy(
        md, defaults=_policy_defaults(defaults or {}, collection, repository, permalink)
    )
    subject_notes = _enforce_approved_subjects(md, approved_subjects)
    if subject_notes:
        policy_notes = policy_notes + subject_notes
    genre_notes = _enforce_approved_genre(md, approved_genre)
    if genre_notes:
        policy_notes = policy_notes + genre_notes
    place_notes = _enforce_approved_places(md, approved_places)
    if place_notes:
        policy_notes = policy_notes + place_notes

    pages_context = []
    for page, (page_bytes, page_mime), page_label_text in zip(present, images, labels):
        source_w, source_h = image_dimensions(str(page))
        sent_w, sent_h = sent_dimensions(page_bytes)
        pages_context.append({
            "filename": page.name,
            "label": page_label_text,
            # source_* is the file on disk; sent_* is what actually reached the model after the
            # MAX_PIXELS cap (docs/DECISIONS.md D-009a). They differ on large scans.
            "source_width": source_w, "source_height": source_h,
            "sent_width": sent_w, "sent_height": sent_h,
            "downscaled": (sent_w, sent_h) != (source_w, source_h),
            "mime": page_mime, "payload_bytes": len(page_bytes),
        })
    context = {
        "item_id": item_id,
        "filename": present[0].name,
        "page_count": len(present),
        "processing_confidence": float(conf),
        "processing_confidence_valid": tesseract_available(),
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": SCHEMA_VERSION,
        "detail": detail,
        "api_calls": len(index_chunks),
        "pages": pages_context,
    }
    if missing_pages:
        context["missing_pages"] = missing_pages
    if ledger:
        context["cost_usd"] = ledger.total_for(item_id)
    if summary_example_ids:
        context["summary_fewshot"] = {
            "mode": summary_fewshot_mode,
            "item_id": item_id,
            "example_count": len(summary_example_ids),
            "example_ids": summary_example_ids,
        }
    context.update(
        _apply_validation(
            md=md,
            transcript=md.get("transcript") or md.get("text_reading"),
            approved_places=approved_places,
            approved_subjects=approved_subjects,
            online_vocab_advisory=online_vocab_advisory,
        )
    )
    context["title_derivation"] = {
        "raw_title": raw_title,
        "normalized_title": normalized_title,
        "applied": bool(title_changed),
        "normalized_title_validation": _normalized_title_validation(
            md=md,
            normalized_title=normalized_title,
            approved_places=approved_places,
            approved_subjects=approved_subjects,
        ),
    }
    if derivation_notes:
        context["derivation_notes"] = derivation_notes
    if title_notes:
        context["title_derivation"]["notes"] = title_notes
    if policy_notes or review_notes:
        context["policy_notes"] = policy_notes + review_notes
    if apply_reviews:
        context["review_applied"] = bool(review_notes)

    envelope = {
        "metadata": md,
        "metadata_tiers": metadata_tiers,
        "field_provenance": field_provenance,
        "context": context,
    }
    validation_error = _validate(md)
    if validation_error:
        envelope["context"]["validation_error"] = validation_error

    os.makedirs(out_dir, exist_ok=True)
    output_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    # A previous failure for this item is now stale.
    stale_failure = Path(out_dir) / f"{item_id}.failed.json"
    if stale_failure.exists():
        stale_failure.unlink()

    spent = ledger.total_for(item_id) if ledger else 0.0
    print(f" Done. (${spent:.4f})" if ledger else " Done.")
    if manifest:
        confidence = (md.get("field_confidence") or {}).get("transcript")
        # Flag on rejections too, not just on an empty field. An item where the model proposed four
        # subjects and only one survived the vocabulary needs review just as much as one that
        # matched nothing -- and it is the more common case on a batch whose subject matter has
        # drifted past the pilot vocabulary.
        vocab_notes = [n for n in (policy_notes or [])
                       if "NEEDS VOCAB REVIEW" in n or n.startswith(("Rejected subject", "Rejected genre", "Place tokens absent"))]
        manifest.add(
            item_id, "ok",
            pages=len(present),
            api_calls=len(index_chunks),
            cost_usd=round(spent, 6),
            transcript_confidence=confidence,
            needs_vocab_review=bool(vocab_notes),
            vocab_notes=vocab_notes or None,
            validation_error=bool(validation_error),
        )
    return "ok"


def is_supported(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".pdf"))


def main() -> None:
    parser = argparse.ArgumentParser(description="mini_loc15: tiny OCR + AI LOC15 metadata pipeline")
    parser.add_argument("--in", dest="inp", default="", help="Local file or directory")
    parser.add_argument("--out", dest="out_dir", default="./out", help="Output directory")
    parser.add_argument("--gdrive", action="store_true", help="Fetch from Google Drive folder first")
    parser.add_argument("--samples", action="store_true", help="Process all .jpg files in SAMPLES/")
    parser.add_argument(
        "--tier",
        choices=sorted(TIERS),
        default="",
        help="Cost tier: luna (cheap bulk) | terra (default) | sol (hard items). Sets the model.",
    )
    parser.add_argument("--model", default="", help="Explicit model id; overrides --tier")
    parser.add_argument(
        "--reasoning-effort",
        default="",
        help="Optional reasoning effort for GPT-5 models (low/medium/high). Omit to use the default.",
    )
    parser.add_argument(
        "--cost-ledger",
        default="",
        help="Path to the append-only cost ledger JSONL (default: <out-dir>/cost_ledger.jsonl)",
    )
    parser.add_argument("--no-cost-ledger", action="store_true", help="Disable cost tracking")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent items (default 1). 4-6 is reasonable; retries back off on rate limits.",
    )
    parser.add_argument(
        "--manifest",
        default="",
        help="Path to the per-item run manifest JSONL (default: <out-dir>/run_manifest.jsonl)",
    )
    parser.add_argument(
        "--per-file",
        action="store_true",
        help="One record per image file instead of per archival item. Multi-page documents and "
             "Recto/Verso pairs then get separate, possibly contradictory records.",
    )
    parser.add_argument(
        "--max-pages-per-call",
        type=int,
        default=DEFAULT_MAX_PAGES_PER_CALL,
        help=f"Pages per API request for multi-page items (default {DEFAULT_MAX_PAGES_PER_CALL}). "
             "Larger items are chunked and merged; the cap keeps requests clear of long-context "
             "pricing, which doubles the input rate.",
    )
    parser.add_argument(
        "--ocr-fallback",
        action="store_true",
        help="Enable the billable vision OCR transcription fallback (default: off). It was 37%% of "
             "the pilot run's cost while returning empty text on several items, because its output "
             "budget is consumed by reasoning tokens. The extraction call already reads the image "
             "at detail=original, so this is usually redundant.",
    )
    parser.add_argument("--prompt-version", default=PROMPT_VERSION, help=f"Prompt version in prompts/ (default: {PROMPT_VERSION})")
    parser.add_argument(
        "--summary-examples-csv",
        default="",
        help="CSV containing approved human Summary examples for few-shot summary prompting",
    )
    parser.add_argument(
        "--summary-fewshot-mode",
        default="leave-one-out",
        choices=["leave-one-out"],
        help="How to include summary examples; leave-one-out excludes the current item's own approved Summary",
    )
    parser.add_argument("--collection", default="", help="Known collection (Tier 3 default)")
    parser.add_argument("--repository", default="", help="Known repository (Tier 3 default)")
    parser.add_argument("--permalink", default="", help="Known permalink (Tier 3 default)")
    parser.add_argument("--series", default="", help="Known series (Tier 3 default)")
    parser.add_argument("--folder", default="", help="Known folder (Tier 3 default)")
    parser.add_argument("--box", default="", help="Known box (Tier 3 default)")
    parser.add_argument("--identifier", default="", help="Known identifier (Tier 3 default)")
    parser.add_argument("--call-number", default="", help="Known call number (Tier 3 default)")
    parser.add_argument("--digital-identifier", default="", help="Known digital identifier (Tier 3 default)")
    parser.add_argument("--reproduction-number", default="", help="Known reproduction number (Tier 3 default)")
    parser.add_argument("--digital-collection", default="", help="Known digital collection (Tier 3 default)")
    parser.add_argument("--digital-publisher", default="", help="Known digital publisher (Tier 3 default)")
    parser.add_argument("--digitized", default="", help="Known digitized flag (true/false; Tier 3 default)")
    parser.add_argument("--approved-places", default="./vocab/fast_places.txt", help="Path to approved FAST place list")
    parser.add_argument(
        "--approved-subjects", default="./vocab/fast_subjects.txt", help="Path to approved reviewed FAST subject list"
    )
    parser.add_argument("--aat-genre", default="vocab/aat_genre.txt", help="Path to approved AAT genre list")
    parser.add_argument(
        "--online-vocab-advisory",
        action="store_true",
        help="Run optional online FAST/AAT checks and record warnings only.",
    )
    parser.add_argument(
        "--validate-vocab",
        action="store_true",
        help="Legacy alias for --online-vocab-advisory (warnings only).",
    )
    parser.add_argument("--dltemp", default="./_gdrive", help="Temp dir for Google Drive downloads")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs")
    parser.add_argument("--apply-reviews", action="store_true", help="Apply review overrides before writing output")
    parser.add_argument(
        "--rebuild-from-existing",
        action="store_true",
        help="Rebuild envelopes from existing JSON outputs without re-running OCR/AI",
    )
    args = parser.parse_args()

    # Resolve the model from --model (explicit) or --tier, defaulting to the standard tier.
    if args.model:
        model = args.model
        tier_label = next((t.name for t in TIERS.values() if t.model_id == model), "custom")
    else:
        tier = TIERS[args.tier or DEFAULT_TIER]
        model, tier_label = tier.model_id, tier.name
    print(f"Model: {model}  (tier: {tier_label}, image detail: {default_detail(model)})")

    ledger: Optional[CostLedger] = None
    if not args.no_cost_ledger:
        ledger_path = args.cost_ledger or str(Path(args.out_dir) / "cost_ledger.jsonl")
        ledger = CostLedger(ledger_path)
        print(f"Cost ledger: {ledger_path}")

    online_vocab_advisory = bool(args.online_vocab_advisory or args.validate_vocab)
    approved_places = _load_controlled_list(args.approved_places)
    approved_subjects = _load_controlled_list(args.approved_subjects)
    approved_genre = _load_controlled_list(args.aat_genre)
    if not approved_places:
        print(f"Warning: approved places list not found or empty: {args.approved_places}")
    if not approved_subjects:
        print(f"Warning: approved subjects list not found or empty: {args.approved_subjects}")
    if not approved_genre:
        print(f"Warning: approved AAT genre list not found or empty: {args.aat_genre}")
    summary_examples = _load_summary_examples(args.summary_examples_csv) if args.summary_examples_csv else {}
    if summary_examples:
        print(f"Loaded {len(summary_examples)} approved Summary examples from {args.summary_examples_csv}")

    paths: List[str] = []
    if args.gdrive:
        if pull_files_from_folder is None:
            raise RuntimeError("Google Drive support not available. Install google-api-python-client and google-auth-oauthlib.")
        folder_id = os.getenv("GDRIVE_FOLDER_ID", "")
        if not folder_id:
            raise RuntimeError("Set GDRIVE_FOLDER_ID when using --gdrive")
        downloads = pull_files_from_folder(folder_id, args.dltemp)
        paths.extend([path for path in downloads if is_supported(path)])

    if args.inp:
        input_path = Path(args.inp)
        if input_path.is_file() and is_supported(str(input_path)):
            paths.append(str(input_path))
        elif input_path.is_dir():
            for file_path in input_path.rglob("*"):
                if file_path.is_file() and is_supported(str(file_path)):
                    paths.append(str(file_path))

    if not paths and not args.gdrive and not args.rebuild_from_existing:
        args.samples = True

    if args.samples and not args.rebuild_from_existing:
        samples_dir = Path("SAMPLES")
        if not samples_dir.exists():
            samples_dir = Path("samples")
        if samples_dir.exists():
            for img_file in sorted(samples_dir.glob("*.jpg")):
                if img_file.is_file():
                    paths.append(str(img_file))
        else:
            print("Warning: SAMPLES/samples directory not found")

    if not paths and not args.rebuild_from_existing:
        print("No inputs. Use --in <path>, --samples, and/or --gdrive.")
        return

    defaults: Dict[str, Any] = {
        "series": args.series or None,
        "folder": args.folder or None,
        "box": args.box or None,
        "identifier": args.identifier or None,
        "call_number": args.call_number or None,
        "digital_identifier": args.digital_identifier or None,
        "reproduction_number": args.reproduction_number or None,
        "digital_collection": args.digital_collection or None,
        "digital_publisher": args.digital_publisher or None,
        "digitized": _parse_bool(args.digitized),
    }
    if args.collection:
        defaults["collection"] = args.collection
    if args.repository:
        defaults["repository"] = args.repository
    if args.permalink:
        defaults["permalink"] = args.permalink

    if args.rebuild_from_existing:
        rebuild_existing_outputs(
            out_dir=args.out_dir,
            defaults=defaults,
            apply_reviews=args.apply_reviews,
            approved_places=approved_places,
            approved_subjects=approved_subjects,
            approved_genre=approved_genre,
            online_vocab_advisory=online_vocab_advisory,
        )
        return

    manifest = RunManifest(args.manifest or str(Path(args.out_dir) / "run_manifest.jsonl"))
    print(f"Run manifest: {manifest.path}")

    # One record per archival item, not per scan. Filenames group pages of the same document
    # (Page_1..N, Recto/Verso, a sequence-numbered volume) -- see app/grouping.py.
    if args.per_file:
        item_groups = {Path(p).stem: [Path(p)] for p in paths}
        print(f"{len(paths)} files, processed individually (--per-file).")
    else:
        item_groups = group_items(paths)
        multi = sum(1 for pages in item_groups.values() if len(pages) > 1)
        print(f"{len(paths)} files -> {len(item_groups)} archival items "
              f"({multi} span multiple pages, max {args.max_pages_per_call} pages per API call).")

    def run_one(item_id: str) -> str:
        pages = item_groups[item_id]
        try:
            return process_item(
                paths=[str(p) for p in pages],
                item_id=item_id,
                max_pages_per_call=args.max_pages_per_call,
                out_dir=args.out_dir,
                collection=args.collection,
                repository=args.repository,
                permalink=args.permalink,
                model=model,
                approved_places=approved_places,
                approved_subjects=approved_subjects,
                approved_genre=approved_genre,
                online_vocab_advisory=online_vocab_advisory,
                output_ext=".loc15.json",
                defaults=defaults,
                overwrite=args.overwrite,
                apply_reviews=args.apply_reviews,
                prompt_version=args.prompt_version,
                summary_examples=summary_examples,
                summary_fewshot_mode=args.summary_fewshot_mode,
                ledger=ledger,
                reasoning_effort=args.reasoning_effort,
                ocr_fallback=args.ocr_fallback,
                manifest=manifest,
            )
        except Exception as exc:
            # Anything outside extraction (OCR, IO, policy) still must not vanish into stdout.
            print(f"x {item_id}: {type(exc).__name__}: {exc}")
            manifest.add(item_id, "failed",
                         error=f"{type(exc).__name__}: {exc}", stage="pipeline")
            return "failed"

    workers = max(1, args.workers)
    item_ids = list(item_groups)
    if workers == 1:
        for item_id in item_ids:
            run_one(item_id)
    else:
        print(f"Running {len(item_ids)} items with {workers} workers.")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, item_id): item_id for item_id in item_ids}
            for future in as_completed(futures):
                future.result()

    counts = manifest.counts()
    print(f"\nOutcome: " + ", ".join(f"{status}={n}" for status, n in sorted(counts.items())))
    failures = manifest.failures()
    if failures:
        print(f"\n{len(failures)} FAILED -- no output written, so a rerun retries them:")
        for record in failures:
            print(f"  {record['item_id']:18} {record.get('error', '')[:96]}")
        print("Rerun the same command to retry only the failures.")

    if ledger and ledger.records:
        billable = [r for r in ledger.records if r.tier != "free"]
        print(f"\nRun cost: ${ledger.total:.4f} over {len(billable)} billable calls "
              f"({len(paths)} items). Ledger: {ledger.path}")
        print("Per-item and per-tier breakdown:  python3 scripts/cost_report.py "
              f"--ledger {ledger.path}")


if __name__ == "__main__":
    main()
