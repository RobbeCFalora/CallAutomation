#!/usr/bin/env python3
"""Hoofdscript: haalt nieuwe Fathom-opnames van Dylan Van Engeland op, stuurt
elke opname door de twee Gemini-agents (Stage 1 -> Stage 2), en schrijft het
resultaat naar Notion.

Draai dit NIET vanuit Claude Cowork - dit praat rechtstreeks met api.fathom.ai,
api.anthropic.com en api.notion.com, en die zijn niet bereikbaar vanuit de
Cowork-sandbox. Zie README.md voor waar je dit wél moet draaien (GitHub
Actions aangeraden).

Gebruik:
    python sync.py                  # normale run: laatste LOOKBACK_HOURS uur
    python sync.py --lookback-hours 48
    python sync.py --dry-run        # haalt meetings op en toont ze, maar
                                     # roept geen Gemini/Notion aan
"""
import argparse
import sys
import traceback

import fathom_client as fc
import pipeline


def main():
    parser = argparse.ArgumentParser(description="Fathom -> Gemini agents -> Notion sync")
    parser.add_argument("--lookback-hours", type=float, default=None,
                         help="Overschrijft LOOKBACK_HOURS uit config/env voor deze run.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Toon welke meetings verwerkt zouden worden, zonder Gemini/Notion aan te roepen.")
    args = parser.parse_args()

    print(f"[sync] Meetings van Dylan Van Engeland ophalen "
          f"(lookback={args.lookback_hours or 'default uit config'}u)...")
    try:
        meetings = fc.get_recent_meetings(lookback_hours=args.lookback_hours)
    except Exception as exc:
        print(f"[sync] FATAL: kon meetings niet ophalen bij Fathom: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[sync] {len(meetings)} meeting(s) gevonden in het lookback-venster.")
    if not meetings:
        print("[sync] Niets te doen. Klaar.")
        return

    successes, failures, skipped = 0, 0, 0

    for meeting in meetings:
        mid = fc.meeting_identifier(meeting)
        mdate = fc.meeting_date(meeting)
        murl = fc.recording_url(meeting)
        transcript = fc.format_transcript(meeting)

        print(f"\n[sync] --- Meeting {mid} (datum: {mdate or 'onbekend'}) ---")

        if fc.is_internal_meeting(meeting):
            print(f"[sync] Intern Falora-gesprek (enkel collega's, geen externe klant/prospect herkend) "
                  f"- overgeslagen, wordt niet geanalyseerd.")
            skipped += 1
            continue

        if not transcript.strip():
            print(f"[sync] Geen transcript-tekst gevonden voor meeting {mid} - overgeslagen "
                  f"(controleer of include_transcript daadwerkelijk data teruggeeft voor dit account).")
            skipped += 1
            continue

        if args.dry_run:
            print(f"[sync] [DRY RUN] zou {len(transcript)} karakters transcript verwerken, "
                  f"link: {murl or '(geen)'}")
            continue

        try:
            report = pipeline.process_meeting(transcript, meeting_date=mdate, recording_url=murl)
            print(f"[sync] Verslag voor meeting {mid}:\n{report}")
            successes += 1
        except Exception:
            print(f"[sync] FOUT bij verwerken van meeting {mid}:", file=sys.stderr)
            traceback.print_exc()
            failures += 1
            # Bewust NIET stoppen: één mislukte meeting mag de rest van de batch
            # niet blokkeren. Dankzij het lookback-venster + Notion's eigen
            # idempotentie-check (Stap 0) wordt een mislukte meeting bij de
            # volgende run automatisch opnieuw geprobeerd.

    print(f"\n[sync] Klaar. {successes} geslaagd, {failures} mislukt, {skipped} overgeslagen "
          f"(van {len(meetings)} gevonden meetings).")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
