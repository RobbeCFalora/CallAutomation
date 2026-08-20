"""Dunne wrapper rond de publieke Notion API (versie 2025-09-03).

Belangrijk: dit praat rechtstreeks met api.notion.com. Dat kan NIET vanuit de
Claude Cowork-sandbox (die staat achter een netwerk-allowlist die Notion niet
bevat) - dit script is bedoeld om buiten Cowork te draaien. Zie README.md.
"""
import re
import requests

from config import NOTION_API_KEY, NOTION_API_URL, NOTION_VERSION, PROPERTY_TYPES

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")


def extract_page_id(url_or_id: str) -> str:
    """Haalt een Notion page-UUID uit een volledige URL of geeft de ID onveranderd terug."""
    match = UUID_RE.search(url_or_id)
    if not match:
        raise ValueError(f"Geen geldige Notion-ID te vinden in: {url_or_id!r}")
    raw = match.group(0).replace("-", "")
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def _format_value(prop_type: str, value):
    if value is None:
        return None
    if prop_type == "title":
        return {"title": [{"text": {"content": str(value)}}]}
    if prop_type == "rich_text":
        text = str(value)
        return {"rich_text": [{"text": {"content": text}}] if text else []}
    if prop_type == "select":
        return {"select": {"name": str(value)}}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type == "url":
        return {"url": str(value) if value else None}
    if prop_type == "date":
        # value is een "YYYY-MM-DD" string, of een dict {"start":..., "end":...}
        if isinstance(value, dict):
            return {"date": {"start": value.get("start"), "end": value.get("end")}}
        return {"date": {"start": value}}
    if prop_type == "relation":
        ids = [extract_page_id(v) for v in value]
        return {"relation": [{"id": i} for i in ids]}
    raise ValueError(f"Onbekend property-type: {prop_type}")


def build_properties(data_source_key: str, values: dict) -> dict:
    """Zet een simpel {veldnaam: waarde}-dict om naar Notion's property-JSON,
    op basis van de schema-mapping in config.PROPERTY_TYPES."""
    schema = PROPERTY_TYPES[data_source_key]
    formatted = {}
    for name, value in values.items():
        if name not in schema:
            raise ValueError(f"Onbekende/niet-schrijfbare property '{name}' voor '{data_source_key}'. "
                              f"Beschikbaar: {list(schema.keys())}")
        formatted_value = _format_value(schema[name], value)
        if formatted_value is not None:
            formatted[name] = formatted_value
    return formatted


def create_page(data_source_id: str, properties: dict, data_source_key: str) -> dict:
    body = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "properties": build_properties(data_source_key, properties),
    }
    r = requests.post(f"{NOTION_API_URL}/pages", headers=HEADERS, json=body, timeout=60)
    r.raise_for_status()
    return r.json()


def update_page(page_id_or_url: str, properties: dict, data_source_key: str) -> dict:
    page_id = extract_page_id(page_id_or_url)
    body = {"properties": build_properties(data_source_key, properties)}
    r = requests.patch(f"{NOTION_API_URL}/pages/{page_id}", headers=HEADERS, json=body, timeout=60)
    r.raise_for_status()
    return r.json()


def query_all(data_source_id: str, page_size: int = 100, max_pages: int = 20) -> list:
    """Haalt ALLE rijen van een data source op (client-side filteren gebeurt erna).
    Notion's publieke API ondersteunt geen vrije SQL - enkel een structured filter,
    en voor een klein/groeiend CRM-achtig datasetje is 'alles ophalen en zelf
    filteren' eenvoudiger en robuuster dan die filter-syntax na te bouwen."""
    results = []
    cursor = None
    for _ in range(max_pages):
        body = {"page_size": page_size}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(f"{NOTION_API_URL}/data_sources/{data_source_id}/query",
                           headers=HEADERS, json=body, timeout=60)
        r.raise_for_status()
        data = r.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def simplify_page(page: dict) -> dict:
    """Reduceert een volledig Notion page-object tot {url, title, <overige velden
    als platte tekst>} - compact genoeg om als tool-resultaat aan het model te geven."""
    out = {"url": page.get("url")}
    for name, prop in page.get("properties", {}).items():
        ptype = prop.get("type")
        if ptype == "title":
            out[name] = "".join(t.get("plain_text", "") for t in prop.get("title", []))
        elif ptype == "rich_text":
            out[name] = "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
        elif ptype == "select":
            out[name] = (prop.get("select") or {}).get("name")
        elif ptype == "checkbox":
            out[name] = prop.get("checkbox")
        elif ptype == "url":
            out[name] = prop.get("url")
        elif ptype == "date":
            out[name] = (prop.get("date") or {}).get("start")
        elif ptype == "relation":
            out[name] = [rel.get("id") for rel in prop.get("relation", [])]
        elif ptype == "formula":
            out[name] = prop.get("formula", {}).get(prop.get("formula", {}).get("type"))
        elif ptype == "rollup":
            out[name] = prop.get("rollup", {}).get(prop.get("rollup", {}).get("type"))
    return out
