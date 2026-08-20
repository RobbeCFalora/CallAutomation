"""Dunne wrapper rond de Google Gemini API (generateContent), inclusief een
generieke "function calling" tool-use loop.

Praat rechtstreeks met generativelanguage.googleapis.com - kan niet vanuit de
Claude Cowork-sandbox, dit script is bedoeld om buiten Cowork te draaien. Zie
README.md.

LET OP - te verifiëren bij de eerste echte run (zie README.md, sectie "Dingen
om te controleren"): Gemini's Schema-object voor function declarations gebruikt
volgens Google's documentatie hoofdletter type-namen ("OBJECT", "STRING", ...).
_to_gemini_type() zet onze schema's daarnaar om. Als Gemini toch een fout geeft
over het schema van een tool, is dit de eerste plek om te checken.
"""
import json
import requests

from config import GEMINI_API_KEY, GEMINI_API_URL, GEMINI_MODEL

HEADERS = {
    "x-goog-api-key": GEMINI_API_KEY,
    "Content-Type": "application/json",
}


def _to_gemini_type(schema):
    """Zet een JSON-schema dict (lowercase 'type': 'object'/'string'/...) recursief
    om naar Gemini's Schema-formaat (uppercase Type-enum: OBJECT, STRING, ...)."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            out["type"] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            out["properties"] = {k: _to_gemini_type(v) for k, v in value.items()}
        elif key == "items":
            out["items"] = _to_gemini_type(value)
        else:
            out[key] = value
    return out


def to_function_declarations(tools: list) -> list:
    """Zet onze tool-lijst ({name, description, input_schema}, zie notion_tools.py)
    om naar Gemini's functionDeclarations-formaat."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "parameters": _to_gemini_type(t["input_schema"]),
        }
        for t in tools
    ]


def call_generate(system: str, contents: list, tools: list = None) -> dict:
    """Eén losse aanroep van de Gemini generateContent API. Geeft de volledige
    response terug."""
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
    }
    if tools:
        body["tools"] = [{"functionDeclarations": to_function_declarations(tools)}]

    url = f"{GEMINI_API_URL}/{GEMINI_MODEL}:generateContent"
    r = requests.post(url, headers=HEADERS, json=body, timeout=300)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini API-fout {r.status_code}: {r.text[:2000]}")
    return r.json()


def _get_parts(response: dict) -> list:
    candidates = response.get("candidates") or []
    if not candidates:
        raise RuntimeError(
            f"Geen candidates in Gemini-respons (mogelijk geblokkeerd door safety filters - "
            f"controleer 'promptFeedback'): {json.dumps(response, ensure_ascii=False)[:1000]}"
        )
    return candidates[0].get("content", {}).get("parts", [])


def extract_text(response: dict) -> str:
    """Plakt alle text-parts van een response aan elkaar (voor Stage 1, zonder tools)."""
    return "".join(p.get("text", "") for p in _get_parts(response) if "text" in p)


def run_agent(system_prompt: str, user_content: str, tools: list, tool_executor, max_turns: int = 15) -> str:
    """Generieke function-calling loop: stuurt user_content naar Gemini met de
    gegeven tools, voert elke functionCall die het model vraagt uit via
    tool_executor(name, args) -> dict, en herhaalt tot het model stopt met
    function-calls (geen functionCall-parts meer in de respons) of max_turns
    bereikt is. Geeft de uiteindelijke tekst (het verslag) terug."""
    contents = [{"role": "user", "parts": [{"text": user_content}]}]

    for turn in range(max_turns):
        response = call_generate(system_prompt, contents, tools=tools)
        parts = _get_parts(response)
        function_calls = [p["functionCall"] for p in parts if "functionCall" in p]

        if not function_calls:
            return "".join(p.get("text", "") for p in parts if "text" in p)

        # Model-turn (met functionCall-parts) toevoegen aan de conversatie
        contents.append({"role": "model", "parts": parts})

        # Elke functionCall uitvoeren en de resultaten teruggeven als functionResponse-parts
        response_parts = []
        for call in function_calls:
            name = call.get("name")
            call_args = call.get("args", {})
            try:
                result = tool_executor(name, call_args)
            except Exception as exc:  # een crashende tool mag de loop niet stukmaken
                result = {"error": str(exc)}
            response_parts.append({
                "functionResponse": {
                    "name": name,
                    "response": result,
                }
            })
        contents.append({"role": "user", "parts": response_parts})

    return "[Gestopt na max_turns zonder definitief antwoord - controleer de laatste Notion-writes handmatig.]"
