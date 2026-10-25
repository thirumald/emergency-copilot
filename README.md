# Emergency Call Co-Pilot: MVP

Reference implementation of the Phase 1 (MVP) slice of the *AI Emergency Call Co-Pilot* concept: a real-time layer that
listens alongside the call-taker, extracts structured incident data, raises critical cues, guides the next SOP question and
pre-fills the CAD record. **The AI only proposes; the call-taker accepts, edits or rejects every field.**

Runs on a laptop with no GPU. The speech and language models are pluggable; this MVP ships deterministic baselines
(lexicon/regex extractor, fuzzy geocoder, rules engine) behind the same interfaces the production models will use.

```bash
pip install -r requirements.txt
python -m copilot            # http://127.0.0.1:8080  (HOST / PORT env vars)
python -m pytest             # 43 tests
python -m copilot.eval       # replay scenarios, score against MVP KPI targets
```

Open the UI, pick a scenario (English, Gulf Arabic + English code-switch, Levantine, Egyptian), press **Start simulated call**.
You can also type caller lines, or use **Mic** (Chrome Web Speech API) for live speech.

## Architecture (mirrors the HLD layers)

```
 audio / text ──► ASR gateway ──► event bus ──► call orchestrator ──► call-taker panel (WebSocket)
 (scripted | browser | Whisper)    (bus.py)      (orchestrator.py)     supervisor wall, admin, audit
                                                   │  ▲
                       extractor · location · reasoner · SOP engine ── audit log ── CAD adapter
```

| Module | HLD component | Catalogue features (P1) |
|---|---|---|
| `speech.py`, `POST /api/calls/{id}/segments`, `/ws/audio` | Media gateway + Speech AI interface | 1, 3, 4*, 6 |
| `lang.py` | Language / dialect ID | 2, 3 |
| `extractor.py` | Fast extractor | 9, 11, 12 |
| `location.py` | Location engine (gazetteer fuzzy + Latin phonetic skeleton + AML fusion) | 17, 19, 21 |
| `reasoner.py` | Severity (explained) and summary | 10, 25 |
| `sop.py` + `data/sop.json` | Deterministic SOP engine, self-ticking checklist | 22, 23 |
| `orchestrator.py` | Call orchestrator, thresholds, human-in-the-loop | 28 |
| `cad.py` | CAD adapters (`MockCAD` writes `var/cad/*.json`, `RestCAD`) | 28 |
| `audit.py` | HMAC hash-chained audit log | 47 |
| `web/` | Call-taker panel, supervisor wall, admin | — |

\* Speaker labels come from the channel (caller / call-taker) rather than diarisation of a mixed channel.

Governance built in: shadow mode (AI computed and logged, hidden from call-takers, nothing written to CAD) with a scoring
endpoint `GET /api/shadow/report` against the call-taker's own entries (`POST /api/calls/{id}/truth`); per-feature kill
switches (`/api/admin/features/{name}`); every transcript line, suggestion, cue, accept/reject/edit and CAD write in the audit
chain (`GET /api/audit/verify` detects any edit, deletion or reorder); call archive with call-taker corrections in
`var/calls/*.json` as the "collect" step of the learning loop.

## Abu Dhabi regions and case record

The gazetteer (`data/gazetteer.json`) covers the three regions of the Emirate: **Abu Dhabi Region** (island, Reem / Maryah,
Saadiyat / Yas, Mussafah, mainland), **Al Ain Region** (city, Jebel Hafeet) and **Al Dhafra Region** (Madinat Zayed, Ruwais,
Liwa, Ghayathi, Al Mirfa). Every place carries `region` and `area`; a handset-only position is mapped to the nearest known place.
Each call gets a **case record** (`casefile.py`, `GET /api/calls/{id}/case`, shown in the call-taker panel):

* case number `AD-<year>-<seq>` (sequence survives restarts), status, caller and language
* region (English / Arabic), area, location with confidence and acceptance status, coordinates, building / floor
* incident type and code, priority, people / injuries / hazards, critical cues
* responding agencies with hotlines and the **nearest hospital / police / civil defence facility** (straight-line km, not ETA)
* data-quality flags (low-confidence location, handset-only position, unacknowledged cues) and a timeline of AI and human events

Reference data (`regions.json`, `facilities.json`, `agencies.json`) is demo data with approximate coordinates. In shadow mode the
case record exposes only the non-AI parts. Unit recommendation and ETA remain Phase 2.

## Use-case showcase page

`web/usecases.html` is a self-contained static page (no server, no CDN, inline icons and illustrations, light/dark, responsive)
for demos and bids: 25 use cases (17 built in the MVP, 8 roadmap) with filter and detail dialogs, a replayable simulated call,
a schematic Abu Dhabi region map, roles, safety model, KPI targets and roadmap. The demo frames come from the real pipeline.
Regenerate after changing scenarios or data with `python scripts/build_usecases.py` (template: `web/usecases.template.html`).
Also served by the app at `/usecases.html`.

## Configuration

| Env var | Purpose |
|---|---|
| `COPILOT_MODE` | `assist` (default) or `shadow` |
| `COPILOT_API_KEY` | If set, all `/api` routes need `X-API-Key` (WebSockets: `?token=`). Use SSO / OIDC in production |
| `COPILOT_AUDIT_KEY` | HMAC key for the audit chain (default is a dev key; use Vault / HSM) |
| `COPILOT_VAR` | Data directory (audit log, CAD mock, call archive) |
| `CAD_URL`, `CAD_TOKEN` | Use the generic `RestCAD` adapter instead of the mock |

## Replacing the baselines with real models

* **ASR:** implement `ASRBackend` (`speech.py`). `FasterWhisperBackend` is included for `/ws/audio/{call_id}` (16 kHz PCM16); it
  is untested and has no streaming partials. The target is a fine-tuned streaming model (Riva / NeMo / Conformer) that
  posts partials to `/segments`. `GET /api/vocabulary` returns the gazetteer words for contextual biasing.
* **Understanding:** `extract()` and `Reasoner` are the seams for a small neural extractor and an LLM running on stable segments.
* **CAD / telephony / GIS:** add an adapter per vendor behind `CADAdapter`; the gazetteer is `data/gazetteer.json`.

## What this MVP is not (read before quoting numbers)

* The sample SOP text, incident taxonomy, gazetteer and cue lexicons are **demo data**, not approved operational protocols.
  They must be replaced and signed off by the client's safety board before any live use.
* `python -m copilot.eval` scores 100% on the four bundled scenarios, but those scenarios were written together with the
  lexicons. This proves the pipeline works end to end, not that accuracy targets are met. WER, dialect accuracy, cue recall and
  location accuracy must be baselined on real call audio during the POC.
* Latency shown is in-process compute only (a few ms). The 800 ms budget also covers audio framing, ASR and network.
* Not built yet (P2/P3 in the catalogue): unit recommendation, CCTV/ANPR fusion, translation/TTS, major-incident mode,
  hoax detection, duplicate detection, QA scoring, training simulator, SIPREC/NG112 ingestion, multi-site HA.
* Single process, in-memory call state and event bus. Production needs Kafka/NATS, Redis state, Kubernetes and SSO.
