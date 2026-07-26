"""Group image files into archival items.

A catalog record describes an ITEM, not a scan. This batch has 316 files covering 130 items:
`AAMU-0003_Page_1..15` are pages of one document, `AAMU-0001_Recto/_Verso` are two sides of one
sheet, and `01_AAMU-0069_Front_cover` starts a 36-page bound volume. Processing per file would mint
a separate title, date and creator for every page -- and for a Recto/Verso pair, two records that
can disagree about the same sheet.

Oversized items are split into chunks rather than sent as one enormous request: at roughly 15,000
image tokens per page, a 36-page item is ~545,000 input tokens, which would cross into OpenAI's
long-context pricing band (2x the input rate) and cost more than processing the pages separately.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# An item number may carry a letter suffix: AAMU-0073a..AAMU-0073e are five distinct items under
# one accession number. Without the optional suffix these split into one record per page.
ITEM_NUMBER = r"[A-Za-z]+-\d+[a-z]?"
# 01_AAMU-0069_Front_cover.jpg -> sequence 01, item AAMU-0069, label Front_cover
SEQ_VOLUME = re.compile(rf"^(\d+)_({ITEM_NUMBER})_(.+)$")
# AAMU-0003_Page_12.jpg / AAMU-0001_Recto.jpg / AAMU-0073a_Page_2.jpg -> item, label
ITEM_LABEL = re.compile(rf"^({ITEM_NUMBER})_(.+)$")
# Tolerates the stray space in AAMU-0093_Page_ 8.jpg and page ranges like Page_2-3, where one
# image captures a two-page spread. Ranges sort by their first page.
PAGE_NUMBER = re.compile(r"^Page[_\s]*(\d+)(?:\s*[-–]\s*\d+)?$", re.IGNORECASE)

# Front matter and back matter sort around the numbered pages.
FRONT_MATTER = ["front_cover", "inside_front_cover", "title_page", "table_of_contents", "contents"]
BACK_MATTER = ["back_cover", "inside_back_cover"]

# Default pages per API call. Keeps the largest request near 100k input tokens, well clear of the
# long-context band, whose exact threshold OpenAI does not publish.
DEFAULT_MAX_PAGES_PER_CALL = 6


def parse_name(stem: str) -> Tuple[str, str, Optional[int]]:
    """Return (item_id, label, sequence) inferred from a filename stem."""
    match = SEQ_VOLUME.match(stem)
    if match:
        return match.group(2), match.group(3), int(match.group(1))
    match = ITEM_LABEL.match(stem)
    if match:
        return match.group(1), match.group(2), None
    return stem, "", None


def _sort_key(path: Path) -> Tuple:
    """Order pages within an item: explicit sequence, then front matter, numbered pages, back matter."""
    _, label, sequence = parse_name(path.stem)
    if sequence is not None:
        return (0, sequence, "")

    lowered = label.lower()
    if lowered in FRONT_MATTER:
        return (1, FRONT_MATTER.index(lowered), "")
    if lowered in BACK_MATTER:
        return (4, BACK_MATTER.index(lowered), "")

    page = PAGE_NUMBER.match(label)
    if page:
        return (2, int(page.group(1)), "")
    if lowered == "recto":
        return (2, 0, "")
    if lowered == "verso":
        return (2, 1, "")
    # Unrecognized labels keep a stable alphabetical order after the numbered pages.
    return (3, 0, lowered)


def group_items(paths: List[str]) -> Dict[str, List[Path]]:
    """Group file paths by archival item, each list ordered by page position."""
    groups: Dict[str, List[Path]] = {}
    for raw in paths:
        path = Path(raw)
        item_id, _, _ = parse_name(path.stem)
        groups.setdefault(item_id, []).append(path)
    for item_id in groups:
        groups[item_id].sort(key=_sort_key)
    return dict(sorted(groups.items()))


def page_label(path: Path) -> str:
    """Human-readable page label for the prompt's page manifest."""
    _, label, sequence = parse_name(path.stem)
    label = label.replace("_", " ").strip() or path.stem
    label = re.sub(r"\bPage\s+(\d+)\b", r"page \1", label, flags=re.IGNORECASE)
    return f"{label} ({sequence:02d})" if sequence is not None else label


def chunk_pages(pages: List[Path], max_per_call: int = DEFAULT_MAX_PAGES_PER_CALL) -> List[List[Path]]:
    """Split an item's pages into request-sized chunks, preserving order."""
    if max_per_call < 1:
        max_per_call = 1
    return [pages[i:i + max_per_call] for i in range(0, len(pages), max_per_call)]
