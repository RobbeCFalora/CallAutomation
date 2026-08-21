"""Orchestratie van de twee LLM-stappen voor één Fathom-meeting:
Stage 1 (Call Analyst, pure extractie) -> Stage 2 (Librarian, schrijft naar Notion).
Gebruikt Gemini (gemini_client.py) als LLM.
"""
import json
import re
from collections import Counter
from pathlib import Path

import gemini_client as llm
import notion_client as nc
import notion_tools
from config import DATA_SOURCES

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _extract_code_block(markdown_text: str) -> str:
    """De prompt-bestanden zijn markdown met toelichting; het eigenlijke system
    prompt staat in het eerste ``` ... ```-codeblok. Dat pikken we eruit."""
    match = re.search(r"```\n(.*?)\n```", markdown_text, re.DOTALL)
    if not match:
        raise ValueError("Geen codeblok gevonden in prompt-bestand")
    return match.group(1)


def load_stage1_prompt() -> str:
    raw = (PROMPTS_DIR / "stage1_analist_prompt.md").read_text(encoding="utf-8")
    return _extract_code_block(raw)


def load_stage2_prompt() -> str:
    raw = (PROMPTS_DIR / "stage2_librarian_prompt.md").read_text(encoding="utf-8")
    return _extract_code_block(raw)


def build_context_lists() -> dict:
    """Haalt de kleine CONTEXT-lijsten op die Stage 1 nodig heeft (bestaande
    categorieën, ICP-segmenten, featurenamen, aannames), rechtstreeks uit Notion.
    Dit blijven bewust korte lijsten van namen/statussen, geen volledige databases."""
    try:
        categories = Counter()
        for p in nc.query_all(DATA_SOURCES["feature_requests"]):
            row = nc.simplify_page(p)
            if row.get("Categorie"):
                categories[row["Categorie"]] += 1
        category_list = sorted(categories.keys())
    except Exception as exc:
        print(f"[pipeline] Kon bestaande categorieën niet ophalen ({exc}) - ga verder met lege lijst.")
        category_list = []

    try:
        segments = set()
        for p in nc.query_all(DATA_SOURCES["icp_signals"]):
            row = nc.simplify_page(p)
            if row.get("ICP segment"):
                segments.add(row["ICP segment"])
        segment_list = sorted(segments)
    except Exception as exc:
        print(f"[pipeline] Kon bestaande ICP-segmenten niet ophalen ({exc}) - ga verder met lege lijst.")
        segment_list = []

    try:
        features = set()
        for p in nc.query_all(DATA_SOURCES["existing_feature_feedback"]):
            row = nc.simplify_page(p)
            if row.get("Feature naam"):
                features.add(row["Feature naam"])
        feature_list = sorted(features)
    except Exception as exc:
        print(f"[pipeline] Kon bestaande featurenamen niet ophalen ({exc}) - ga verder met lege lijst.")
        feature_list = []

    try:
        assumptions = []
        for p in nc.query_all(DATA_SOURCES["assumptions"]):
            row = nc.simplify_page(p)
            if row.get("Aanname"):
                assumptions.append(f"{row['Aanname']} ({row.get('Huidige status', 'onbekend')})")
    except Exception as exc:
        print(f"[pipeline] Kon bestaande aannames niet ophalen ({exc}) - ga verder met lege lijst.")
        assumptions = []

    return {
        "categories": category_list,
        "segments": segment_list,
        "features": feature_list,
        "assumptions": assumptions,
    }


def render_stage1_prompt(context: dict) -> str:
    prompt = load_stage1_prompt()
    prompt = prompt.replace(
        "{{lijst van reeds gebruikte categorienamen}}",
        ", ".join(context["categories"]) or "(nog geen)",
    )
    prompt = prompt.replace(
        "{{lijst van reeds gedefinieerde segmenten}}",
        ", ".join(context["segments"]) or "(nog geen)",
    )
    prompt = prompt.replace(
        "{{lijst van featurenamen}}",
        ", ".join(context["features"]) or "(nog geen)",
    )
    prompt = prompt.replace(
        "{{lijst van aannames + confirmed/contradicted/untested}}",
        "; ".join(context["assumptions"]) or "(nog geen)",
    )
    return prompt


def _parse_json_response(text: str) -> dict:
    """Stage 1 moet pure JSON teruggeven, maar we vangen defensief op als het
    model er toch een ```json-codeblok omheen zet."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text)


def run_stage1(transcript_text: str, meeting_date: str = "") -> dict:
    """Stage 1: pure extractie, geen tools. Geeft de geparste JSON terug.

    Vraagt Gemini expliciet om JSON-output (responseMimeType) - dat dwingt
    syntactisch geldige JSON af en voorkomt de occasionele kapotte JSON die een
    los taalmodel soms teruggeeft. Als het parsen tóch faalt (zeldzaam), wordt
    de aanroep één keer opnieuw geprobeerd voor we opgeven - dit gesprek zou
    anders sowieso overgeslagen worden en pas bij een volgende run opnieuw
    geprobeerd worden, dus deze retry bespaart gewoon tijd binnen dezelfde run."""
    context = build_context_lists()
    system_prompt = render_stage1_prompt(context)
    user_content = (
        f"Datum van dit gesprek: {meeting_date or 'onbekend'}\n\n"
        f"TRANSCRIPT:\n{transcript_text}"
    )
    user_parts = [{"role": "user", "parts": [{"text": user_content}]}]
    generation_config = {"responseMimeType": "application/json"}

    last_error = None
    for attempt in range(2):
        response = llm.call_generate(system_prompt, user_parts, generation_config=generation_config)
        text = llm.extract_text(response)
        try:
            return _parse_json_response(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            print(f"[pipeline] Stage 1 gaf geen geldige JSON terug (poging {attempt + 1}/2): {exc} - "
                  f"{'opnieuw proberen...' if attempt == 0 else 'geef op.'}")
    raise last_error


def run_stage2(stage1_json: dict, meeting_date: str, recording_url: str) -> str:
    """Stage 2: de Librarian, MET Notion-tools. Geeft het tekstverslag terug."""
    system_prompt = load_stage2_prompt()
    user_content = (
        f"Datum van dit gesprek (gebruik dit voor het 'Datum'-veld van de Meeting-pagina, en voor "
        f"de idempotentie-check in Stap 0): {meeting_date or 'onbekend'}\n"
        f"Transcript-link (gebruik dit voor het 'Transcript link'-veld van de Meeting-pagina): "
        f"{recording_url or '(geen link beschikbaar)'}\n\n"
        f"Stage 1 JSON-output van de Call Analyst:\n{json.dumps(stage1_json, ensure_ascii=False, indent=2)}"
    )
    return llm.run_agent(system_prompt, user_content, notion_tools.TOOLS, notion_tools.execute_tool)


def process_meeting(transcript_text: str, meeting_date: str = "", recording_url: str = "") -> str:
    """Volledige pipeline voor één meeting: Stage 1 -> Stage 2. Geeft Stage 2's
    verslag terug (of gooit een exception als er iets grondig mis ging - de
    caller in sync.py vangt dat per meeting op zodat één mislukt gesprek de
    rest van de batch niet blokkeert)."""
    stage1_json = run_stage1(transcript_text, meeting_date)
    return run_stage2(stage1_json, meeting_date, recording_url)
