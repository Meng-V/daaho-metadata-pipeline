"""FAST place headings: one table of variant -> authorized forms, shared by every place check.

Before this module there were three hard-coded copies of the Washington, D.C. mapping (in main,
validation_core and the vocabulary builder), each slightly different, and no way to express any
other correction. The table now lives in vocab/fast_place_variants.txt. See docs/DECISIONS.md D-015.
"""

import unicodedata
from pathlib import Path
from typing import Dict, Optional, Union

DEFAULT_VARIANTS_PATH = Path(__file__).resolve().parent.parent / "vocab" / "fast_place_variants.txt"


def _norm(value: str) -> str:
    # NFC so "Kōbe" typed with a combining macron matches the precomposed form in the vocabulary.
    return " ".join(unicodedata.normalize("NFC", value).strip().split()).lower()


def load_place_variants(path: Optional[Union[str, Path]] = None) -> Dict[str, str]:
    path = Path(path) if path else DEFAULT_VARIANTS_PATH
    table: Dict[str, str] = {}
    if not path.exists():
        return table
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "=>" not in line:
            raise ValueError(f"{path}:{number}: expected 'variant => authorized', got {raw!r}")
        variant, authorized = (part.strip() for part in line.split("=>", 1))
        table[_norm(variant)] = unicodedata.normalize("NFC", authorized)
    return table


PLACE_VARIANTS = load_place_variants()


def canonical_place(token: str, variants: Optional[Dict[str, str]] = None) -> str:
    """The FAST authorized form for a known variant; otherwise the token as written."""
    table = PLACE_VARIANTS if variants is None else variants
    return table.get(_norm(token), unicodedata.normalize("NFC", token.strip()))
