# Job Listing Notifier

Scrapes defense/federal contractor career sites, filters listings through a
local LLM (Qwen3.5-9B via llama.cpp), and posts qualifying matches to Discord.

## How it works

```
main_scraper.py  (every 4h, CPU only)
    -> hits each configured company's ATS API (Workday CXS, etc.)
    -> dedups against jobs.db and stores new raw listings

main_filter.py   (7 AM / 6 PM, GPU)
    -> Layer 1: title keyword filter        (filters/title_filter.py)
    -> Layer 2: regex requirement extraction (filters/regex_extractor.py)
    -> Layer 3: local LLM judgment          (filters/llm_judge.py)
    -> starts/stops a llama.cpp server around the batch so VRAM is only
       held during inference
    -> PASS/FLAG results are posted to Discord; REJECTs are logged silently

main_digest.py   (weekly, GPU)
    -> LLM-summarizes the week's PASS/FLAG listings into one ranked message
```

All state lives in a single SQLite file (`jobs.db`, gitignored) with four
tables: `raw_listings`, `filtered_listings`, `scraper_log`, `llm_log`.

## Project layout

```
config/       companies.yaml, roles.yaml, filters.yaml, settings.yaml
scrapers/     base.py (interface) + workday.py (Workday CXS API)
filters/      title_filter.py, regex_extractor.py, llm_judge.py
notifiers/    discord.py
storage/      database.py (SQLite), models.py (JobListing)
utils/        logging.py, health.py
main_scraper.py / main_filter.py / main_digest.py   entry points
```

## Setup

```bash
pip install -r requirements.txt
```

Set your Discord webhook via environment variable (preferred over editing
`config/settings.yaml` directly, so the secret never lands in the repo):

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

Place the GGUF model at the path configured in `config/settings.yaml` ->
`llm.model_path` (default `models/qwen3.5-9b-ud-q6_k_xl.gguf`), and make sure
`llama-server` (llama.cpp) is on your `PATH`.

## Usage

```bash
python main_scraper.py   # scrape configured Workday companies into jobs.db
python main_filter.py    # run the 3-layer filter + LLM judge, notify Discord
python main_digest.py    # weekly LLM-summarized digest of PASS/FLAG listings
```

### Scheduling (Windows Task Scheduler)

| Task | Schedule | Command |
|------|----------|---------|
| Scraper | Every 4 hours | `python main_scraper.py` |
| Filter | Daily 7:00 AM | `python main_filter.py` |
| Filter | Daily 6:00 PM | `python main_filter.py` |
| Digest | Sunday 8:00 AM | `python main_digest.py` |

## Configuration

- `config/companies.yaml` — target companies, ATS type, API endpoints
- `config/roles.yaml` — title-match keyword tiers and exclusion lists
- `config/filters.yaml` — experience caps, clearance policy, education gates
- `config/settings.yaml` — scraper/LLM/Discord/logging tuning

## Status

**Phase 1 (MVP)** — done: 9 Workday companies scraped end-to-end
(Booz Allen, Leidos, GDIT, Northrop Grumman, RTX, CACI, MITRE, KBR, Amentum).
Accenture Federal Services has a config entry but its SmartRecruiters scraper
is not yet implemented.

**Not yet implemented** (see original project plan for full scope):
- Phase 2: Peraton (iCIMS), SAIC (Oracle Cloud HCM), CGI Federal (njoyn)
- Phase 3: Lockheed Martin (BrassRing), HII Mission Technologies (custom board)
- Phase 4: clearance tracker, error alerting on repeated scraper failure,
  listing-expiry detection, dashboard, config hot-reload

## Known gaps / next steps

- No automated tests yet.
- The Amentum Workday tenant/server/site values in `companies.yaml` are
  unverified — check `amentumcareers.com` before relying on that scrape.
- `main_filter.py` and `main_digest.py` assume `llama-server` is already
  installed and on `PATH`.
