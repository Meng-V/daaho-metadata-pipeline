"""Repair [page N] markers that restart in a merged multi-request transcript.

Items longer than max_pages_per_call are sent in several requests and their transcripts joined.
Each request used to be told only about its own images, so every request numbered from [page 1]:
AAMU-0028's seven pages read 1-6 then 1 again, and nine items in the 2026-07 batch were affected.
The transcription policy (R4) numbers pages by their position in the whole item.

A marker number that does not increase can only be a restart, since the policy numbers pages
strictly in order. Each restart continues from the last page reached. The result is accepted only
if it is exactly 1..page_count; anything else is left as it was and reported, never guessed at.
"""

import re
from typing import Dict, List, Optional, Tuple

PAGE_MARKER = re.compile(r"^(\s*)\[page (\d+)\](\s*)$", re.MULTILINE)


def page_numbers(transcript: Optional[str]) -> List[int]:
    return [int(m.group(2)) for m in PAGE_MARKER.finditer(transcript or "")]


def renumber_restarted_pages(
    transcript: Optional[str], page_count: int
) -> Tuple[Optional[str], Optional[Dict[str, object]], Optional[str]]:
    """Return (transcript, repair_record, note).

    repair_record is set when markers were renumbered, for the record's context; note is set when
    something changed or when markers restart but could not be repaired safely.
    """
    numbers = page_numbers(transcript)
    if not any(later <= earlier for earlier, later in zip(numbers, numbers[1:])):
        return transcript, None, None

    absolute: List[int] = []
    offset = 0
    previous_raw = 0
    for raw in numbers:
        if absolute and raw <= previous_raw:
            offset = absolute[-1]
        absolute.append(raw + offset)
        previous_raw = raw

    if absolute != list(range(1, page_count + 1)):
        return transcript, None, (
            f"NEEDS PAGE REVIEW: page markers restart ({numbers}) but do not renumber cleanly to "
            f"1..{page_count}; left as written."
        )

    replacement = iter(absolute)
    fixed = PAGE_MARKER.sub(lambda m: f"{m.group(1)}[page {next(replacement)}]{m.group(3)}", transcript or "")
    record = {"from": numbers, "to": f"1-{page_count}", "reason": "markers restarted at each request batch"}
    note = f"Renumbered page markers that restarted at each request batch: {numbers} -> 1..{page_count}."
    return fixed, record, note
