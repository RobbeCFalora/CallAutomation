"""Wrapper rond de Fathom API (List Meetings) om nieuwe opnames van Dylan Van
Engeland op te halen, inclusief transcript.

LET OP - te verifiëren bij de eerste echte run (zie README.md, sectie
"Dingen om te controleren"): de exacte namen van het paginatie-cursor-veld en
van de top-level envelope-sleutel in de JSON-respons staan niet 100% vast in
de publieke docs die ik kon raadplegen. Deze client is defensief geschreven:
hij probeert meerdere veelvoorkomende varianten voordat hij opgeeft, en drukt
een duidelijke waarschuwing af als geen enkele variant werkt, in plaats van
stil verkeerde data te verwerken.

Praat rechtstreeks met api.fathom.ai - kan niet vanuit de Claude Cowork-
sandbox, dit script is bedoeld om buiten Cowork te draaien. Zie README.md.
"""
import sys
from datetime import datetime, timedelta, timezone

import requests

from config import (
    FATHOM_API_KEY, FATHOM_BASE_URL, FATHOM_RECORDED_BY_EMAIL, FALORA_EMAIL_DOMAIN, LOOKBACK_HOURS,
)

HEADERS = {
    "X-Api-Key": FATHOM_API_KEY,
    "Content-Type": "application/json",
}

# Mogelijke sleutels waaronder de lijst meetings in de JSON-respons kan zitten.
_RESULT_KEYS = ["items", "meetings", "data", "results"]
# Mogelijke sleutels voor de paginatie-cursor.
_CURSOR_KEYS = ["next_cursor", "cursor", "next_page_token"]
# Mogelijke sleutels waaronder de lijst deelnemers/uitgenodigden van een meeting
# kan zitten, en de sleutel(s) voor hun e-mailadres binnen zo'n item.
_INVITEE_LIST_KEYS = ["calendar_invitees", "invitees", "meeting_invitees", "attendees"]
_INVITEE_EMAIL_KEYS = ["email", "email_address"]


def _extract_items(payload: dict) -> list:
    for key in _RESULT_KEYS:
        if key in payload and isinstance(payload[key], list):
            return payload[key]
    # Fallback: als de payload zelf al een lijst is (sommige APIs doen dat)
    if isinstance(payload, list):
        return payload
    print(f"[fathom_client] WAARSCHUWING: kon geen lijst met meetings vinden in de respons-sleutels "
          f"{list(payload.keys()) if isinstance(payload, dict) else type(payload)}. "
          f"Controleer de Fathom API-docs en pas _RESULT_KEYS aan.", file=sys.stderr)
    return []


def _extract_cursor(payload: dict):
    if not isinstance(payload, dict):
        return None
    for key in _CURSOR_KEYS:
        if payload.get(key):
            return payload[key]
    return None


def get_recent_meetings(lookback_hours: float = None) -> list:
    """Haalt de meetings van Dylan Van Engeland op die binnen het lookback-venster
    zijn opgenomen, MET transcript. Retourneert een lijst van meeting-dicts
    (ruwe Fathom-vorm - zie pipeline.py voor hoe we die verwerken)."""
    lookback_hours = lookback_hours if lookback_hours is not None else LOOKBACK_HOURS
    created_after = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    all_items = []
    cursor = None
    for _ in range(50):  # hard cap tegen een eventuele kapotte paginatie-loop
        params = {
            "recorded_by[]": FATHOM_RECORDED_BY_EMAIL,
            "created_after": created_after,
            "include_transcript": "true",
        }
        if cursor:
            params["cursor"] = cursor

        r = requests.get(f"{FATHOM_BASE_URL}/meetings", headers=HEADERS, params=params, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Fathom API-fout {r.status_code}: {r.text[:2000]}")
        payload = r.json()

        items = _extract_items(payload)
        all_items.extend(items)

        cursor = _extract_cursor(payload)
        if not cursor or not items:
            break

    return all_items


def format_transcript(meeting: dict) -> str:
    """Zet de transcript-array van een meeting om naar leesbare tekst
    ('Spreker: tekst' per regel). Verwacht shape:
    [{speaker: {display_name, matched_calendar_invitee_email}, text, timestamp}, ...]
    - valt terug op een paar alternatieve veldnamen als die niet exact matchen."""
    transcript = meeting.get("transcript") or meeting.get("transcription") or []
    lines = []
    for entry in transcript:
        speaker = entry.get("speaker") or {}
        name = speaker.get("display_name") or speaker.get("name") or "Onbekende spreker"
        text = entry.get("text") or entry.get("content") or ""
        if text:
            lines.append(f"{name}: {text}")
    return "\n".join(lines)


def _attendee_emails(meeting: dict) -> list:
    """Best-effort lijst van attendee e-mailadressen van deze meeting. Probeert
    een paar gangbare Fathom-veldnamen voor de deelnemerslijst (zelfde
    defensieve aanpak als _RESULT_KEYS hierboven); valt terug op de sprekers in
    het transcript (die soms een gekoppeld calendar-invitee e-mailadres hebben)
    als er geen apart deelnemersveld gevonden wordt."""
    for key in _INVITEE_LIST_KEYS:
        invitees = meeting.get(key)
        if isinstance(invitees, list) and invitees:
            emails = []
            for inv in invitees:
                if not isinstance(inv, dict):
                    continue
                for ekey in _INVITEE_EMAIL_KEYS:
                    if inv.get(ekey):
                        emails.append(inv[ekey])
                        break
            if emails:
                return emails

    transcript = meeting.get("transcript") or meeting.get("transcription") or []
    emails = []
    for entry in transcript:
        speaker = entry.get("speaker") or {}
        email = speaker.get("matched_calendar_invitee_email")
        if email:
            emails.append(email)
    return emails


def is_internal_meeting(meeting: dict) -> bool:
    """True als dit een intern Falora-gesprek is (enkel collega's aanwezig, geen
    externe klant/prospect) - zo'n gesprek mag NIET als sales-call
    geanalyseerd worden (bv. Dylan met Gauthier/Stijn).

    Detectie: als ALLE attendee e-mailadressen die we kunnen vinden op
    FALORA_EMAIL_DOMAIN eindigen, is het intern. Kunnen we helemaal geen
    e-mailadres achterhalen (onbekende Fathom-veldnaam, zie README), dan
    behandelen we het gesprek voorzichtigheidshalve als NIET intern - een
    gemist/onbekend veld mag nooit stilzwijgend een echt klantgesprek laten
    verdwijnen. Controleer bij twijfel met --dry-run of dit correct herkend
    wordt."""
    emails = _attendee_emails(meeting)
    if not emails:
        return False
    domain_suffix = "@" + FALORA_EMAIL_DOMAIN.lower().lstrip("@")
    return all(e.lower().strip().endswith(domain_suffix) for e in emails)


def meeting_identifier(meeting: dict) -> str:
    """Best-effort unieke identifier van een meeting, voor logging (niet voor
    idempotentie - die gebeurt in Notion zelf, zie stage2-librarian-prompt.md)."""
    return str(meeting.get("id") or meeting.get("meeting_id") or meeting.get("url") or meeting.get("share_url") or "onbekend-id")


def meeting_date(meeting: dict) -> str:
    """Best-effort datum (YYYY-MM-DD) waarop de meeting werd opgenomen."""
    raw = (
        meeting.get("created_at")
        or meeting.get("scheduled_start_time")
        or meeting.get("recording_start_time")
        or meeting.get("started_at")
        or ""
    )
    return raw[:10] if raw else ""


def recording_url(meeting: dict) -> str:
    """Best-effort link naar de opname/transcript in Fathom, voor het
    'Transcript link'-veld op de Meeting-pagina."""
    return meeting.get("url") or meeting.get("share_url") or meeting.get("recording_url") or ""
