"""Configuratie: alles komt uit environment variables. Nooit keys hardcoden."""
import os

try:
    # Optioneel: als python-dotenv geïnstalleerd is en er een .env-bestand
    # bestaat (lokaal testen), laad die in os.environ. In GitHub Actions zijn
    # de env vars al gezet via "Secrets" en doet dit gewoon niets.
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Fathom ---
FATHOM_API_KEY = os.environ["FATHOM_API_KEY"]
# Fathom-account e-mailadres van Dylan Van Engeland (voor de recorded_by[]-filter,
# zodat we ENKEL zijn gesprekken meenemen en niet die van heel het bedrijf).
FATHOM_RECORDED_BY_EMAIL = os.environ["FATHOM_RECORDED_BY_EMAIL"]
FATHOM_BASE_URL = "https://api.fathom.ai/external/v1"

# Hoe ver terug in de tijd we bij elke run kijken. Groter dan het schema-interval
# zetten (bv. 26u bij een uurlijkse cron) zodat een gemiste of trage run nooit een
# gesprek overslaat. Dubbele verwerking wordt opgevangen door de idempotentie-check
# die Stage 2 zelf in Notion doet (zie prompts/stage2_librarian_prompt.md, Stap 0).
LOOKBACK_HOURS = float(os.environ.get("LOOKBACK_HOURS") or "26")

# --- Gemini (Google) ---
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
# Vul hier het model-ID in dat je op https://aistudio.google.com terugvindt
# (bv. "gemini-2.0-flash" of "gemini-2.5-pro" - check de actuele modelnamen zelf,
# want die veranderen). Bewust geen default hardcoded: een stille verkeerde
# default is erger dan een duidelijke crash bij het opstarten.
GEMINI_MODEL = os.environ["GEMINI_MODEL"]
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# --- Notion ---
# Internal integration token van een Notion-integratie die je zelf aanmaakt op
# https://www.notion.so/profile/integrations, en die je vervolgens deelt met de
# "Falora Call Intelligence"-pagina (zie README, stap "Notion-integratie").
NOTION_API_KEY = os.environ["NOTION_API_KEY"]
NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"

# Data source IDs van de databases die we in Notion hebben opgezet.
# (Zie ook prompts/stage2_librarian_prompt.md, dat exact dezelfde IDs gebruikt.)
DATA_SOURCES = {
    "meetings": "307af664-8353-4383-96a0-95851ed3832c",
    "outcome_reasons": "38135297-4246-4d6a-90dd-5e11b5323147",
    "feature_requests": "7c1833cb-583e-45f7-be29-ce3e6d2b0bac",
    "existing_feature_feedback": "80eefb64-32ac-4006-992a-37a0962f028c",
    "client_insights": "669f6396-564e-42ec-9904-2f3f0f7adfe7",
    "positioning_signals": "c3c39dda-9f92-41b5-acaa-4d0a2e77a3ce",
    "blockers_decisions": "985452e5-bee5-4215-831b-62db5e4873d4",
    "action_items": "425ae994-2929-4711-8943-7e8d68936a5d",
    "icp_signals": "289bc874-a069-4070-8bb5-dcd4af4f129f",
    "assumptions": "c8326f79-81e6-4268-967f-42e6de40bda0",
    "assumption_mentions": "ad063bc6-be4d-4f95-b6c4-b3f786192eb1",
}

# Per data source: welke properties er zijn en van welk Notion-type. Enkel
# schrijfbare properties (rollups en formules staan hier bewust niet in, want
# die worden automatisch berekend door Notion en kunnen niet gezet worden).
PROPERTY_TYPES = {
    "meetings": {
        "Meeting naam": "title", "Bedrijf/Klant": "rich_text", "Datum": "date",
        "Deal stage": "select", "Industrie": "rich_text", "Bedrijfsgrootte": "rich_text",
        "Funding stage": "rich_text", "Attendees": "rich_text", "Call outcome": "select",
        "Transcript link": "url",
    },
    "outcome_reasons": {
        "Beschrijving": "title", "Richting": "select", "Categorie": "select",
        "Genoemd door": "rich_text", "Meeting": "relation",
    },
    "feature_requests": {
        "Beschrijving": "title", "Categorie": "select", "Expliciet/impliciet": "select",
        "Vraagsterkte": "select", "Status": "select", "Genoemd door": "rich_text",
        "Onderbouwing": "rich_text", "Meeting": "relation",
    },
    "existing_feature_feedback": {
        "Beschrijving": "title", "Feature naam": "rich_text", "Sentiment": "select",
        "Genoemd door": "rich_text", "Onderbouwing": "rich_text", "Meeting": "relation",
    },
    "client_insights": {
        "Beschrijving": "title", "Tag": "select", "Ernst": "select",
        "Expliciet/impliciet": "select", "Genoemd door": "rich_text",
        "Onderbouwing": "rich_text", "Meeting": "relation",
    },
    "positioning_signals": {
        "Beschrijving": "title", "Signaaltype": "select", "Concurrent genoemd": "rich_text",
        "Genoemd door": "rich_text", "Meeting": "relation",
    },
    "blockers_decisions": {
        "Beschrijving": "title", "Type": "select", "Eigenaar": "rich_text",
        "Geen eigenaar": "checkbox", "Status": "select", "Meeting": "relation",
    },
    "action_items": {
        "Commitment": "title", "Eigenaar": "rich_text", "Deadline": "date",
        "Afgerond": "checkbox", "Meeting": "relation",
    },
    "icp_signals": {
        "Signaal": "title", "ICP segment": "rich_text", "Industrie": "rich_text",
        "Bedrijfsgrootte": "rich_text", "Funding stage": "rich_text",
        "Fit signaal": "select", "Uitkomst": "rich_text", "Onderbouwing": "rich_text",
        "Meeting": "relation",
    },
    "assumptions": {
        "Aanname": "title", "Huidige status": "select",
    },
    "assumption_mentions": {
        "Naam": "title", "Aanname": "relation", "Meeting": "relation",
        "Evidentie": "rich_text", "Status op dit moment": "select",
    },
}
