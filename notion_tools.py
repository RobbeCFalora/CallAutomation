"""Tool-definities die aan het LLM (Stage 2, de 'Librarian', draait op Gemini) worden gegeven, plus de
dispatcher die een tool_use-aanroep effectief tegen Notion uitvoert."""
import json

import notion_client as nc
from config import DATA_SOURCES

DATA_SOURCE_KEYS = list(DATA_SOURCES.keys())

TOOLS = [
    {
        "name": "notion_list_existing",
        "description": (
            "Haal de bestaande rijen van één Falora Call Intelligence-database op, "
            "als compacte {url, ...velden}-objecten. Gebruik dit VOORDAT je iets "
            "aanmaakt in feature_requests, existing_feature_feedback, icp_signals of "
            "assumptions, om te checken of er al een gelijkaardige rij bestaat "
            "(zie Stap 2 van je instructies) - en gebruik dit ook op 'meetings' voor "
            "de idempotentie-check in Stap 0."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_source": {"type": "string", "enum": DATA_SOURCE_KEYS},
            },
            "required": ["data_source"],
        },
    },
    {
        "name": "notion_create_page",
        "description": (
            "Maak een nieuwe rij aan in één van de Falora Call Intelligence-databases. "
            "'properties' is een plat {veldnaam: waarde}-object met de EXACTE Nederlandse "
            "veldnamen (bv. 'Beschrijving', 'Meeting', 'Ernst'). Voor een relation-veld "
            "geef je een lijst van Notion-URL's (bv. de Meeting-pagina). Voor select-velden "
            "geef je de exacte Notion-optiewaarde (zie de mapping-tabel in je instructies, "
            "bv. 'High' i.p.v. 'high')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_source": {"type": "string", "enum": DATA_SOURCE_KEYS},
                "properties": {"type": "object"},
            },
            "required": ["data_source", "properties"],
        },
    },
    {
        "name": "notion_update_page",
        "description": (
            "Werk een bestaande rij bij (bv. om een Meeting-relatie toe te voegen aan een "
            "bestaande Feature Request/ICP Signal/Assumption in plaats van een duplicaat "
            "aan te maken, of om Vraagsterkte/Status te verhogen). Geef ENKEL de velden op "
            "die je wilt wijzigen. Voor een relation-veld: geef de VOLLEDIGE nieuwe lijst "
            "van URL's (bestaande + nieuwe), niet enkel de toevoeging - haal dus eerst met "
            "notion_list_existing de huidige waarde op als je aan een relation-array toevoegt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_source": {"type": "string", "enum": DATA_SOURCE_KEYS},
                "page_url": {"type": "string", "description": "URL of ID van de te updaten pagina"},
                "properties": {"type": "object"},
            },
            "required": ["data_source", "page_url", "properties"],
        },
    },
]


def execute_tool(name: str, tool_input: dict) -> dict:
    try:
        if name == "notion_list_existing":
            ds_key = tool_input["data_source"]
            pages = nc.query_all(DATA_SOURCES[ds_key])
            return {"rows": [nc.simplify_page(p) for p in pages]}

        if name == "notion_create_page":
            ds_key = tool_input["data_source"]
            page = nc.create_page(DATA_SOURCES[ds_key], tool_input["properties"], ds_key)
            return {"created": True, "url": page.get("url")}

        if name == "notion_update_page":
            ds_key = tool_input["data_source"]
            page = nc.update_page(tool_input["page_url"], tool_input["properties"], ds_key)
            return {"updated": True, "url": page.get("url")}

        return {"error": f"Onbekende tool: {name}"}
    except Exception as exc:  # een tool-fout mag de hele run niet crashen
        return {"error": str(exc)}
