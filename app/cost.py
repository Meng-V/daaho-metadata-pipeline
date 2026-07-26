"""Model tiers, pricing, and a per-call cost ledger.

Every billable API call is recorded to a JSONL ledger so cost can be reported per image, per
tier, and per call type. The ledger is append-only and survives crashes, so a partial run still
has accurate accounting for what it did spend.

Two things cost money per image, and they are tracked separately:

  ocr_fallback  -- app.ai_metadata.transcribe_with_model(), a vision call made only when
                   Tesseract returns almost nothing. Skipped on most typed documents.
  extraction    -- app.ai_metadata.extract_metadata(), the main vision + metadata call. Always.

Tesseract OCR itself runs locally and costs nothing; it is recorded with zero cost so the
report can show that explicitly rather than leaving a reader to wonder.

Prices are per 1,000,000 tokens, taken from https://developers.openai.com/api/docs/pricing
as of 2026-07-25. Verify before relying on a projection -- see PRICING_VERIFIED_ON.
"""

import json
import os
import sys
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional

PRICING_VERIFIED_ON = "2026-07-25"
PRICING_SOURCE = "https://developers.openai.com/api/docs/pricing"

# ---------------------------------------------------------------------------------------------
# Billing calibration
#
# The ledger prices the API's own reported token counts at OpenAI's PUBLISHED LIST RATES. On
# 2026-07-26 that produced $31.15 against an actual billed $19.70 on the platform usage dashboard
# for the same window -- the ledger overstated by 58%.
#
# The published rates were re-verified and are correct, and the request counts line up, so this is
# not a transcription error in the table below. Comparing per-model totals:
#
#     terra   ledger $26.103   billed $16.464   ratio 0.631
#     sol     ledger $ 5.043   billed $ 3.235   ratio 0.641
#
# Two ratios that close together across different models indicate an account-level discount of
# roughly 36%, not a token-counting fault. (Per-category ratios vary from 0.58 to 0.69, so the
# cached/uncached split in this ledger does not match how the dashboard buckets tokens; that
# affects the category breakdown but not the total.)
#
# The cause is not documented anywhere this code can read, so it is NOT baked into the rates.
# Reports show list price and, when a factor is set, the calibrated figure beside it -- always
# saying which is which. Set it from an observed dashboard total:
#
#     BILLING_CALIBRATION=0.6325 python3 scripts/cost_deliverable.py
#
# Re-derive it whenever the billing arrangement might have changed. THE DASHBOARD IS AUTHORITATIVE
# for what was actually charged; this ledger is authoritative for relative cost -- which item, tier
# or call type consumed what share -- because those ratios hold under any uniform discount.
BILLING_CALIBRATION = float(os.getenv("BILLING_CALIBRATION", "0")) or None
CALIBRATION_OBSERVED_ON = "2026-07-26"
CALIBRATION_NOTE = (
    "List prices overstated the actual bill by 58% on 2026-07-26 "
    "($31.15 ledger vs $19.70 billed). Set BILLING_CALIBRATION to reconcile; "
    "the platform usage dashboard is authoritative for amounts charged."
)


@dataclass(frozen=True)
class Tier:
    name: str
    model_id: str
    input_per_m: float
    cached_input_per_m: float
    output_per_m: float
    intent: str


# Three tiers, cheapest first. All three are GPT-5.6 and therefore support
# detail="original", which is the capability this project actually needs -- see
# docs/DECISIONS.md D-009.
TIERS: Dict[str, Tier] = {
    "luna": Tier(
        name="luna",
        model_id="gpt-5.6-luna",
        input_per_m=1.00,
        cached_input_per_m=0.10,
        output_per_m=6.00,
        intent="Bulk tier. Clean typed documents, good contrast, no handwriting.",
    ),
    "terra": Tier(
        name="terra",
        model_id="gpt-5.6-terra",
        input_per_m=2.50,
        cached_input_per_m=0.25,
        output_per_m=15.00,
        intent="Default tier. Typed documents with some difficulty; newspaper clippings.",
    ),
    "sol": Tier(
        name="sol",
        model_id="gpt-5.6-sol",
        input_per_m=5.00,
        cached_input_per_m=0.50,
        output_per_m=30.00,
        intent="Hard tier. Handwriting, damage, dense multi-column pages, linter-flagged reruns.",
    ),
}

DEFAULT_TIER = "terra"

# Models seen with no price on file. Warned about once each, loudly: a silent $0 row in a budget
# report is worse than no report, so an unpriced model must never pass quietly.
_WARNED_UNKNOWN: set = set()


def tier_for_model(model_id: str) -> Optional[Tier]:
    for tier in TIERS.values():
        if tier.model_id == model_id:
            return tier
    return None


def rates_for_model(model_id: str) -> tuple:
    """Return (input_per_m, cached_input_per_m, output_per_m, tier_name, is_estimated).

    An unknown model yields zero rates flagged as estimated, and warns once. Add the model to
    TIERS to price it properly rather than letting a run accumulate untracked spend.
    """
    tier = tier_for_model(model_id)
    if tier:
        return tier.input_per_m, tier.cached_input_per_m, tier.output_per_m, tier.name, False

    if model_id not in _WARNED_UNKNOWN:
        _WARNED_UNKNOWN.add(model_id)
        print(
            f"\nWARNING: no pricing on file for model {model_id!r}. Its calls will be ledgered at "
            f"$0.00 and flagged as estimated, so the cost report will UNDERSTATE this run.\n"
            f"         Add it to TIERS in app/cost.py with rates from {PRICING_SOURCE}.\n",
            file=sys.stderr,
        )
    return 0.0, 0.0, 0.0, "unknown", True


@dataclass
class CallRecord:
    """One billable (or explicitly free) unit of work."""

    item_id: str
    call_type: str                  # ocr_fallback | extraction | tesseract
    model: str
    tier: str
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    image_tokens: int = 0           # broken out when the API reports it
    cost_input: float = 0.0
    cost_cached: float = 0.0
    cost_output: float = 0.0
    cost_total: float = 0.0
    pricing_estimated: bool = False
    prompt_version: str = ""
    detail: str = ""
    note: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


def _usage_int(usage: Any, *names: str) -> int:
    """Pull an int off a usage object or dict, tolerating SDK shape changes."""
    for name in names:
        if usage is None:
            return 0
        if isinstance(usage, dict):
            value = usage.get(name)
        else:
            value = getattr(usage, name, None)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _usage_nested(usage: Any, container: str, *names: str) -> int:
    if usage is None:
        return 0
    inner = usage.get(container) if isinstance(usage, dict) else getattr(usage, container, None)
    return _usage_int(inner, *names) if inner is not None else 0


def record_from_usage(
    item_id: str,
    call_type: str,
    model: str,
    usage: Any,
    prompt_version: str = "",
    detail: str = "",
    note: str = "",
) -> CallRecord:
    """Build a priced CallRecord from an OpenAI usage payload."""
    input_rate, cached_rate, output_rate, tier_name, estimated = rates_for_model(model)

    prompt_tokens = _usage_int(usage, "prompt_tokens", "input_tokens")
    completion_tokens = _usage_int(usage, "completion_tokens", "output_tokens")
    cached_tokens = _usage_nested(usage, "prompt_tokens_details", "cached_tokens")
    if not cached_tokens:
        cached_tokens = _usage_nested(usage, "input_tokens_details", "cached_tokens")
    image_tokens = _usage_nested(usage, "prompt_tokens_details", "image_tokens")
    reasoning_tokens = _usage_nested(usage, "completion_tokens_details", "reasoning_tokens")

    # Cached input bills at the cached rate; the remainder at the full input rate.
    cached_tokens = min(cached_tokens, prompt_tokens)
    uncached = max(0, prompt_tokens - cached_tokens)

    cost_input = uncached / 1_000_000 * input_rate
    cost_cached = cached_tokens / 1_000_000 * cached_rate
    cost_output = completion_tokens / 1_000_000 * output_rate

    return CallRecord(
        item_id=item_id,
        call_type=call_type,
        model=model,
        tier=tier_name,
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        image_tokens=image_tokens,
        cost_input=round(cost_input, 8),
        cost_cached=round(cost_cached, 8),
        cost_output=round(cost_output, 8),
        cost_total=round(cost_input + cost_cached + cost_output, 8),
        pricing_estimated=estimated,
        prompt_version=prompt_version,
        detail=detail,
        note=note,
    )


def free_record(item_id: str, call_type: str, note: str = "") -> CallRecord:
    """A unit of work that runs locally and costs nothing (Tesseract)."""
    return CallRecord(item_id=item_id, call_type=call_type, model="local", tier="free", note=note)


class CostLedger:
    """Append-only JSONL ledger. Safe to use across runs; entries accumulate.

    Thread-safe, because a concurrent run has several workers billing at once and a torn write
    would corrupt the accounting.
    """

    def __init__(self, path: Optional[str]):
        self.path = Path(path) if path else None
        self.records: List[CallRecord] = []
        self._lock = threading.Lock()
        if self.path:
            os.makedirs(self.path.parent, exist_ok=True)

    def add(self, record: CallRecord) -> CallRecord:
        with self._lock:
            self.records.append(record)
            if self.path:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        return record

    @property
    def total(self) -> float:
        with self._lock:
            return round(sum(r.cost_total for r in self.records), 6)

    def total_for(self, item_id: str) -> float:
        """Cost attributable to one item.

        Never derive a per-item cost by differencing `total` around the work: with concurrent
        workers that delta includes whatever other items happened to finish in the window, which
        inflated the printed figures on the first batch run (BC-0697 showed $0.6362 against an
        actual $0.0905).
        """
        with self._lock:
            return round(sum(r.cost_total for r in self.records if r.item_id == item_id), 6)

    def summary_line(self) -> str:
        with self._lock:
            billable = [r for r in self.records if r.tier != "free"]
        if not billable:
            return "no billable calls"
        return f"{len(billable)} calls, ${self.total:.4f}"


def load_ledger(path: str) -> List[Dict[str, Any]]:
    """Read a ledger JSONL back into dicts, skipping malformed lines."""
    records = []
    ledger_path = Path(path)
    if not ledger_path.exists():
        return records
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
