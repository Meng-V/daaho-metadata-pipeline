from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict

class AAMUBCMetadataModel(BaseModel):
    """Pydantic model matching the AAMU-BC Metadata Upload Spreadsheet columns."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    # Core identification fields
    identifier: Optional[str] = Field(default=None, alias="Identifier")
    title: Optional[str] = Field(default=None, alias="Title")
    series: Optional[str] = Field(default=None, alias="Series")
    issue: Optional[str] = Field(default=None, alias="Issue")
    
    # Creator/Contributor fields
    creator: Optional[str] = Field(default=None, alias="Creator")
    contributors: Optional[str] = Field(default=None, alias="Contributors")
    correspondents: Optional[str] = Field(default=None, alias="Correspondents")
    
    # Date and publication fields
    date: Optional[str] = Field(default=None, alias="Date")
    publisher: Optional[str] = Field(default=None, alias="Publisher")
    location: Optional[str] = Field(default=None, alias="Location")
    
    # Description fields
    summary: Optional[str] = Field(default=None, alias="Summary")
    extent: Optional[str] = Field(default=None, alias="Extent")
    dimensions: Optional[str] = Field(default=None, alias="Dimensions")
    
    # Subject fields (appear to be semicolon-separated lists in CSV)
    subject_fast: Optional[str] = Field(default=None, alias="Subject (FAST)")
    subject_people: Optional[str] = Field(default=None, alias="Subject (People)")
    subject_local: Optional[str] = Field(default=None, alias="Subject (Local)")
    decade: Optional[str] = Field(default=None, alias="Decade")
    
    # Classification fields
    theme: Optional[str] = Field(default=None, alias="Theme")
    genre: Optional[str] = Field(default=None, alias="Genre")
    type: Optional[str] = Field(default=None, alias="Type")
    language: Optional[str] = Field(default=None, alias="Language")
    
    # Repository and collection fields
    repository: Optional[str] = Field(default=None, alias="Repository")
    collection: Optional[str] = Field(default=None, alias="Collection")
    folder: Optional[str] = Field(default=None, alias="Folder")
    rights: Optional[str] = Field(default=None, alias="Rights")
    
    # Digital fields
    digital_collection: Optional[str] = Field(default=None, alias="Digital Collection")
    digital_publisher: Optional[str] = Field(default=None, alias="Digital Publisher")
    digitized: Optional[str] = Field(default=None, alias="Digitized")
    transcript: Optional[str] = Field(default=None, alias="Transcript")
    
    # Additional identifier fields (note: CSV has duplicate "Identifier" column, typically renamed to "Identifier.1" by parsers)
    identifier_1: Optional[str] = Field(default=None, alias="Identifier.1")
    preservation_filename: Optional[str] = Field(default=None, alias="Preservation Filename")
    object_id: Optional[str] = Field(default=None, alias="Object ID")


# Fields a reviewer triages on. field_confidence carries one honest 0-100 score per entry so a
# solo reviewer can sort by confidence instead of re-checking everything (docs/DECISIONS.md D-008).
FIELD_CONFIDENCE_FIELDS = [
    "title",
    "date",
    "place",
    "creator",
    "contributors",
    "correspondents",
    "transcript",
    "description",
    "subjects",
    "genre",
    "language",
]

# Keep the original LOC15_SCHEMA for backward compatibility
LOC15_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title":  {"type": "string", "minLength": 1, "maxLength": 240},
        "creator":{"type": ["string", "null"], "maxLength": 200},
        "contributors":{"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 8},
        "correspondents":{"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 12},
        "publisher":{"type": ["string", "null"], "maxLength": 160},
        "date":   {"type": ["string", "null"], "pattern": r"^\d{4}(-\d{2}(-\d{2})?)?$"},
        # An array since schema v3, like every other multi-valued field: sender/creation place first,
        # then recipient. Was one semicolon-joined string (docs/DECISIONS.md D-014).
        # One heading per item: no semicolon (a joined list) and no comma ("Oxford, Ohio"). The pattern
        # used to require "State--City", which rejects FAST's own headings for D.C. and city-states --
        # "Washington (D.C.)", "Singapore" -- and flagged 18 valid records. Whether a heading is right
        # is decided by vocab/fast_places.txt, not by its shape (D-015).
        "place":  {"type": ["array", "null"], "items": {"type": "string", "maxLength": 80, "pattern": r"^[^;,]+$"}, "maxItems": 6},
        "language":{"type": ["string", "null"], "maxLength": 80},

        "subjects": {"type": ["array", "null"], "items": {"type": "string", "maxLength": 80}, "maxItems": 8},
        "theme": {"type": ["array", "null"], "items": {"type": "string", "maxLength": 80}, "maxItems": 6},
        "genre": {"type": ["array", "null"], "items": {"type": "string", "maxLength": 80}, "maxItems": 6},
        "keywords": {"type": ["array", "null"], "items": {"type": "string", "maxLength": 80}, "maxItems": 12},
        "decade": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{4}$"},

        "description": {"type": ["string", "null"], "maxLength": 1000},
        "collection":  {"type": ["string", "null"], "maxLength": 200},
        "series":      {"type": ["string", "null"], "maxLength": 200},
        "folder":      {"type": ["string", "null"], "maxLength": 120},
        "box":         {"type": ["string", "null"], "maxLength": 120},

        "format":      {"type": ["string", "null"], "maxLength": 80},
        "medium":      {"type": ["string", "null"], "maxLength": 120},
        "type":        {"type": ["string", "null"], "maxLength": 120},
        "rights":      {"type": ["string", "null"], "maxLength": 240},
        "repository":  {"type": ["string", "null"], "maxLength": 200},

        "identifier":  {"type": ["string", "null"], "maxLength": 160},
        "call_number": {"type": ["string", "null"], "maxLength": 120},
        "digital_identifier":  {"type": ["string", "null"], "maxLength": 160},
        "reproduction_number": {"type": ["string", "null"], "maxLength": 160},
        "permalink":           {"type": ["string", "null"], "maxLength": 240},

        "digital_collection": {"type": ["string", "null"], "maxLength": 200},
        "digital_publisher":  {"type": ["string", "null"], "maxLength": 200},
        "digitized":          {"type": ["boolean", "null"]},

        "transcript":     {"type": ["string", "null"]},
        "text_reading":   {"type": ["string", "null"]},
        "generated_title":{"type": ["string", "null"], "maxLength": 240},
        # Declared with explicit keys, not additionalProperties. OpenAI structured outputs
        # strict mode requires every object to set additionalProperties:false and list all
        # properties in "required", so a free-key map cannot be expressed. It previously came
        # back null on every item, which silently defeated the field's purpose.
        "field_confidence": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                name: {"type": ["integer", "null"], "minimum": 0, "maximum": 100}
                for name in FIELD_CONFIDENCE_FIELDS
            },
            "required": list(FIELD_CONFIDENCE_FIELDS),
        },
    },
    "required": [
        "title","creator","contributors","correspondents","publisher","date","place","language",
        "subjects","theme","genre","keywords","decade","description","collection","series","folder","box",
        "format","medium","type","rights","repository",
        "identifier","call_number","digital_identifier","reproduction_number","permalink",
        "digital_collection","digital_publisher","digitized",
        "transcript","text_reading","generated_title","field_confidence"
    ]
}

MAX_OCR_CHARS = 12000
# Must cover reasoning tokens AND the visible response, because reasoning models bill both against
# max_completion_tokens. Measured on the 19-image pilot: reasoning consumed 56-100% of the old 4096
# budget, and BC-0897's first attempt spent all 4096 on reasoning and returned an EMPTY response,
# forcing a retry. Output is billed per token actually used, so a generous ceiling costs nothing
# and removes a silent-truncation failure mode that would recur on longer documents.
MAX_OUTPUT_TOKENS = 12000
DEFAULT_MODEL = "gpt-5.6-terra"
SCHEMA_VERSION = "loc15_schema_v3"

# Trust tiers for policy enforcement and labeling (ordered for deterministic output).
TIER1_FIELDS = [
    "transcript",
    "text_reading",
    "description",
    "title",
    "generated_title",
    "date",
    "contributors",
    "correspondents",
    "place",
    "keywords",
    "decade",
]
TIER2_FIELDS = [
    "subjects",
    "genre",
    "creator",
    "publisher",
    "theme",
]
TIER3_FIELDS = [
    "rights",
    "repository",
    "collection",
    "series",
    "folder",
    "box",
    "identifier",
    "call_number",
    "digital_identifier",
    "reproduction_number",
    "permalink",
    "digital_collection",
    "digital_publisher",
    "digitized",
]

TIER3_DEFAULTABLE_FIELDS = [
    "repository",
    "collection",
    "series",
    "folder",
    "box",
    "identifier",
    "call_number",
    "digital_identifier",
    "reproduction_number",
    "permalink",
    "digital_collection",
    "digital_publisher",
    "digitized",
]

FIELD_PROVENANCE_LABELS = {
    "title": "AI-Generated Title",
    "description": "AI-Generated Summary",
    "transcript": "OCR Transcript",
    "text_reading": "OCR Text Reading",
    "generated_title": "AI-Generated Title (Alternate)",
    "date": "AI-Inferred Date",
    "contributors": "AI-Extracted Names (People)",
    "correspondents": "AI-Extracted Names (People)",
    "place": "AI-Extracted Places",
    "keywords": "AI-Generated Keywords",
    "decade": "AI-Inferred Decade",
    "subjects": "AI-Proposed Subject",
    "genre": "AI-Proposed Genre",
    "creator": "AI-Proposed Creator",
    "publisher": "AI-Proposed Publisher",
    "theme": "AI-Proposed Theme",
    "rights": "Human-only Rights (blank)",
    "repository": "Human-only Repository (blank)",
    "collection": "Human-only Collection (blank)",
    "series": "Human-only Series (blank)",
    "folder": "Human-only Folder (blank)",
    "box": "Human-only Box (blank)",
    "identifier": "Human-only Identifier (blank)",
    "call_number": "Human-only Call Number (blank)",
    "digital_identifier": "Human-only Digital Identifier (blank)",
    "reproduction_number": "Human-only Reproduction Number (blank)",
    "permalink": "Human-only Permalink (blank)",
    "digital_collection": "Human-only Digital Collection (blank)",
    "digital_publisher": "Human-only Digital Publisher (blank)",
    "digitized": "Human-only Digitized Flag (blank)",
}
