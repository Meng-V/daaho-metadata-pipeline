from typing import Dict, Any, List

SAMPLE_HEADERS = [
    "Identifier","Title","Series","Issue","Creator","Contributors","Correspondents","Date",
    "Publisher","Location","Description","Subject","Theme","Genre","Type","Language",
    "Repository","Collection","Folder","Rights","Digital Collection","Digital Publisher",
    "Digitized","Transcript","Identifier.1","Preservation Filename","Object ID"
]

def to_sample_row(envelope: Dict[str, Any]) -> Dict[str, str]:
    md = envelope.get("metadata", {})
    ctx = envelope.get("context", {})
    normalized_title = (ctx.get("title_derivation") or {}).get("normalized_title")
    def join(vals):
        if not vals: return ""
        if isinstance(vals, list): return "; ".join([str(v) for v in vals if v])
        return str(vals)

    row = {
        "Identifier": md.get("identifier") or md.get("digital_identifier") or "",
        "Title": normalized_title or md.get("title") or md.get("generated_title") or "",
        "Series": md.get("series") or "",
        "Issue": "",
        "Creator": md.get("creator") or "",
        "Contributors": join(md.get("contributors")),
        "Correspondents": join(md.get("correspondents")),
        "Date": md.get("date") or "",
        "Publisher": md.get("publisher") or "",
        "Location": join(md.get("place")),
        "Description": md.get("description") or "",
        "Subject": join(md.get("subjects")),
        "Theme": join(md.get("theme")),
        "Genre": join(md.get("genre")),
        "Type": md.get("type") or md.get("format") or "",
        "Language": md.get("language") or "",
        "Repository": md.get("repository") or "",
        "Collection": md.get("collection") or "",
        "Folder": md.get("folder") or "",
        "Rights": md.get("rights") or "",
        "Digital Collection": md.get("digital_collection") or "",
        "Digital Publisher": md.get("digital_publisher") or "",
        "Digitized": "Yes" if md.get("digitized") else "",
        "Transcript": md.get("transcript") or md.get("text_reading") or "",
        "Identifier.1": md.get("digital_identifier") or "",
        "Preservation Filename": ctx.get("filename",""),
        "Object ID": md.get("call_number") or md.get("reproduction_number") or "",
    }
    return row
