# Fathom → Gemini agents → Notion sync

Dit script haalt automatisch nieuwe salesgesprekken van **Dylan Van Engeland** op uit
Fathom, stuurt elk gesprek door twee Gemini-stappen (extractie → Notion-schrijven), en
schrijft het resultaat weg in de "Falora Call Intelligence"-databases in Notion.

```
Fathom (nieuwe opname) → Stage 1 "Call Analyst" (extractie naar JSON)
                        → Stage 2 "Librarian" (matcht tegen bestaande Notion-rijen,
                          schrijft/updatet Notion)
```

## Waar moet dit draaien? (belangrijk)

**Niet in Claude Cowork.** Dit script praat rechtstreeks met `api.fathom.ai`,
`generativelanguage.googleapis.com` (Gemini) en `api.notion.com` via gewone HTTP-calls. De Cowork-sandbox
waarin ik dit voor je gebouwd heb, zit achter een netwerk-allowlist die deze domeinen
niet toelaat (getest: een directe call naar Fathom's API werd daar geblokkeerd door de
proxy). Dit is dus bewust een op-zichzelf-staand script, bedoeld om **buiten** Cowork
te draaien. Drie opties, van makkelijkst naar meest controle:

1. **GitHub Actions (aangeraden)** — gratis voor dit gebruik, geen server om te
   onderhouden, draait automatisch op een schema. Er staat al een werkende workflow
   klaar in `.github/workflows/sync.yml` die standaard elk uur draait. Stappen:
   - Maak een (private!) GitHub-repo aan en push deze hele map erin.
   - Ga naar **Settings → Secrets and variables → Actions** en voeg de secrets toe die
     hieronder bij "API-keys" staan (`FATHOM_API_KEY`, `FATHOM_RECORDED_BY_EMAIL`,
     `GEMINI_API_KEY`, `GEMINI_MODEL`, `NOTION_API_KEY`; `LOOKBACK_HOURS` is
     optioneel).
   - Klaar — de workflow draait vanaf dan automatisch. Je kan hem ook handmatig
     starten via het "Actions"-tabblad ("Run workflow"), bv. om te testen.
2. **Je eigen computer (goed om eerst te testen)** — zie "Lokaal testen" hieronder.
   Werkt, maar je computer moet dan aanstaan wanneer je wil dat er gesynchroniseerd
   wordt, dus niet ideaal voor iets dat continu moet lopen.
3. **Een klein VPS'je** (bv. een goedkope Hetzner/DigitalOcean-instance) met een cronjob
   die `python sync.py` periodiek aanroept — enkel nodig als je liever geen GitHub
   Actions gebruikt of frequenter dan elk uur wil synchroniseren.

## API-keys die je nodig hebt

| Env var | Waar te vinden |
|---|---|
| `FATHOM_API_KEY` | De admin/team API-key die je al had. |
| `FATHOM_RECORDED_BY_EMAIL` | Het Fathom-account e-mailadres van Dylan Van Engeland — dit filtert zodat ENKEL zijn gesprekken worden meegenomen, niet die van heel het bedrijf. |
| `GEMINI_API_KEY` | aistudio.google.com/apikey → "Create API key" (gratis account volstaat om te starten). |
| `GEMINI_MODEL` | Het model-ID dat je wil gebruiken, bv. `gemini-2.0-flash` of `gemini-2.5-pro` — check de actuele lijst op aistudio.google.com of in de Gemini API-docs. Bewust geen default in de code, zodat je zelf een bewuste keuze maakt (en zodat je meteen een duidelijke foutmelding krijgt als je hem vergeet in te vullen, in plaats van een stille verkeerde default). |
| `NOTION_API_KEY` | Maak een "internal integration" op notion.so/profile/integrations, en deel die integratie vervolgens met de "🧠 Falora Call Intelligence"-pagina in Notion (··· → Connect to → jouw integratie). Zonder die laatste stap krijgt het script een 403 van Notion. |

Zie `.env.example` voor het volledige lijstje (inclusief de optionele `LOOKBACK_HOURS` en
`FALORA_EMAIL_DOMAIN`).

## Interne gesprekken worden overgeslagen

Gesprekken waarbij alle deelnemers een e-mailadres op `FALORA_EMAIL_DOMAIN` hebben (default
`stretchinnovation.be`) - dus geen externe klant/prospect aanwezig, bv. Dylan met Gauthier of Stijn - worden
automatisch overgeslagen en NIET naar de Gemini-agents/Notion gestuurd (`is_internal_meeting()` in
`fathom_client.py`). Kan geen enkel e-mailadres van de deelnemers achterhaald worden (zie caveat
hieronder over onbekende Fathom-veldnamen), dan wordt het gesprek voorzichtigheidshalve WEL verwerkt
- controleer dit dus bij de eerste run met `--dry-run` (die toont "Intern Falora-gesprek... -
overgeslagen" in de output als het herkend wordt).

## Lokaal testen

```bash
cd fathom-notion-sync
python -m venv venv && source venv/bin/activate      # of je eigen manier van venv'en
pip install -r requirements.txt
cp .env.example .env
# ... vul .env aan met je echte keys ...
python sync.py --dry-run          # toont welke meetings gevonden worden, zonder
                                   # Gemini of Notion aan te roepen
python sync.py                    # echte run
```

`.env` wordt automatisch geladen (via `python-dotenv`) als het bestaat — dat is enkel
voor lokaal testen. In GitHub Actions komen de env vars uit de Secrets, niet uit `.env`.

## Hoe het idempotent blijft (geen dubbele Notion-rijen)

- Elke run kijkt terug tot `LOOKBACK_HOURS` uur geleden (standaard 26u). Zet dit ruim
  groter dan je schema-interval (bv. 26u bij een uurlijkse cron), zodat een gemiste of
  trage run nooit een gesprek overslaat.
- Dat betekent dat een gesprek soms **meerdere keren** aan het script wordt aangeboden
  (bv. elk uur opnieuw, tot het buiten het lookback-venster valt). Dat is opzettelijk
  eenvoudig gehouden: in plaats van dat het script zelf een lijst "al verwerkte
  meetings" moet bijhouden (extra staat, extra faalpunten), doet **Stage 2 zelf** een
  check in Notion (Stap 0 in `prompts/stage2_librarian_prompt.md`): bestaat er al een
  Meeting-rij met dezelfde klant + datum? Dan stopt Stage 2 en schrijft niets weg.
- Dit is dezelfde aanpak die we al live getest hebben binnen Cowork (met de
  Optimile-call), dus het patroon zelf is bewezen — enkel de "buitenkant" (dit script)
  is nieuw.

## Dingen om te controleren bij de allereerste echte run

Ik heb dit script zo defensief mogelijk geschreven, maar een paar stukken kon ik niet
100% bevestigen tegen de officiële documentatie zonder een echte test-run:

0. **Gemini's function-calling schema (Stage 2)** — `gemini_client.py` zet onze
   tool-definities (in `notion_tools.py`) om naar Gemini's verwachte formaat, met
   hoofdletter type-namen ("OBJECT", "STRING", ...) volgens Google's documentatie.
   Als de eerste Stage 2-run een fout geeft over een ongeldig tool-schema, is dit de
   eerste plek om te checken (`_to_gemini_type()` in `gemini_client.py`). Test dit dus
   bij voorkeur eerst met één echt transcript (niet `--dry-run`, die roept geen LLM
   aan) voor je het op de automatische planning zet.

1. **De naam van het paginatie-cursor-veld** in de JSON-respons van "List Meetings" —
   `fathom_client.py` probeert een paar gangbare varianten (`next_cursor`, `cursor`,
   `next_page_token`). Als Fathom een andere naam gebruikt, verwerkt het script gewoon
   maar 1 pagina (geen crash, maar mogelijk mis je meetings als er in één run meer dan
   1 pagina resultaten is).
2. **De top-level sleutel** waaronder de lijst meetings in die JSON-respons staat
   (`items`, `meetings`, `data`, `results` worden geprobeerd). Als geen van die klopt,
   print het script een duidelijke `WAARSCHUWING`-regel in de logs in plaats van stil
   0 meetings te verwerken.

Draai bij twijfel eerst `python sync.py --dry-run` en kijk naar de output (aantal
gevonden meetings, en of de WAARSCHUWING verschijnt). Als er een probleem is: open de
respons van Fathom (bv. met een simpele `curl` vanaf je eigen computer/terminal — dat
domein is bij jou niet geblokkeerd) en pas `_RESULT_KEYS` / `_CURSOR_KEYS` in
`fathom_client.py` aan naar wat je daar echt ziet.

Ook `include_transcript=true` (of de exacte transcript-shape) kan in de praktijk licht
afwijken — `format_transcript()` in `fathom_client.py` valt terug op een paar
alternatieve veldnamen, maar controleer bij de eerste run dat de transcript-tekst er
goed uitkomt (`--dry-run` toont het aantal karakters, niet de inhoud; laat gerust de
eerste echte niet-dry-run met 1 gesprek draaien en check het Stage 1-resultaat).

## Projectstructuur

```
fathom-notion-sync/
├── sync.py                  # hoofdscript / entrypoint
├── pipeline.py              # orkestreert Stage 1 -> Stage 2 per meeting
├── fathom_client.py         # Fathom API: meetings ophalen + transcript parsen
├── gemini_client.py         # Gemini generateContent API + generieke function-calling loop
├── notion_client.py         # Notion API wrapper (pages/data_sources)
├── notion_tools.py          # Tool-definities + dispatcher voor Stage 2
├── config.py                # alle configuratie (uit env vars)
├── prompts/
│   ├── stage1_analist_prompt.md
│   └── stage2_librarian_prompt.md
├── .github/workflows/sync.yml
├── requirements.txt
├── .env.example
└── .gitignore
```

## Nog niet getest / bekende beperking

Cross-call deduplicatie (dezelfde feature/ICP-segment/aanname die in een *tweede,
ander* gesprek terugkomt en correct samengevoegd wordt in plaats van gedupliceerd) is
tot nu toe maar met één echt transcript getest. De logica staat er (Stap 2 in
`stage2-librarian-prompt.md`), maar reken er niet blind op tot je dit met een tweede
gesprek hebt gezien werken — controleer de eerste paar keer even zelf in Notion of
samenvoegingen kloppen.
