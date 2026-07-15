# HANDOFF — MTGO Modern metagame & matchup analysis tool

**For:** a fresh agent continuing this build in `/home/ben/linux-code`.
**Read this + `PLAN.md` (approved plan) first.** This file records everything already
done and — critically — the non-obvious data-access findings so you don't re-derive them.

---

## TL;DR of current state
- Toolchain fully set up (uv + Python 3.14.6 + mypy + pytest). Project scaffolded.
- The hard problem — **reliably fetching complete MTGO event data** — is SOLVED (see below).
- Real test fixtures are saved. Next step is writing `parse.py` (task #2, in progress) and onward.
- Nothing has been committed to git. Don't commit unless the user asks.

---

## ✅ Already done
- **uv** installed at `~/.local/bin/uv` (add to PATH: `export PATH="$HOME/.local/bin:$PATH"`).
- **Python 3.14.6** installed via uv; project **`.venv`** created on it. `.python-version` = `3.14`.
- **mypy 2.3.0** + **pytest 9.1.1** installed in the venv. Run tools via `uv run <cmd>`.
- Files written:
  - `pyproject.toml` — project metadata, `[project.scripts] mtgmodern = "mtgmodern.cli:main"`,
    **`[tool.mypy] strict = true`** (+ extra strict flags), `[dependency-groups] dev`.
  - `.python-version`, updated `.gitignore` (ignores `.venv/`, `.mypy_cache/`, `data/raw/`, etc.).
  - `mtgmodern/__init__.py` (has `__version__`), `mtgmodern/py.typed`.
  - `PLAN.md` (copy of the approved plan), `HANDOFF.md` (this file).
- Directories: `mtgmodern/  config/  data/raw/  data/processed/  tests/fixtures/`.
- **Fixtures saved** (real MTGO data, full payload):
  - `tests/fixtures/challenge_event.json` — Modern Showcase Challenge, 32 decklists,
    32 standings, 32 winloss, 3 brackets (top-8 playoff). Full card lists present.
  - `tests/fixtures/challenge_event_small.json` — same shape trimmed to 4 players (fast tests).

## Task list (in the harness)
1. ✅ Set up uv + Python + mypy/pytest
2. 🔄 Build `parse.py` + tests  ← **START HERE**
3. Build `archetype.py` + tests
4. Build `fetch.py` + `storage.py` + tests
5. Build `discover.py` + `analyze.py` + tests
6. Build `cli.py` + `run.py` + end-to-end smoke run

---

## 🔑 CRITICAL DATA-ACCESS FINDINGS (do not re-derive — hard-won)

### 1. Where the data lives
MTGO event pages (`https://www.mtgo.com/decklist/<slug>`) are JS-rendered but embed a JSON
blob in the HTML:
```
window.MTGO.decklists.data = { ... };
```
Extract with regex `r'window\.MTGO\.decklists\.data\s*=\s*(\{.*?\});'` + `re.S`, then `json.loads`.

**Verified top-level keys:** `event_id, description, starttime, format, type, inplayoffs, url,
site_name, decklists, brackets, standings, winloss, final_rank, player_count`.

- `decklists[]`: `{loginid, tournamentid, decktournamentid, player, main_deck[], sideboard_deck[]}`.
  Each card entry: `{qty, sideboard, docid, card_attributes:{card_name, cost, rarity, color,
  cardset, card_type, colors[]}}`. **Use `card_attributes.card_name` + `qty` for archetype rules.**
- `standings[]`: `{loginid, login_name, rank, score, opponentmatchwinpercentage,
  gamewinpercentage, opponentgamewinpercentage, eliminated}`.
- `winloss[]`: `{loginid, wins, losses}` — per-player AGGREGATE match W/L across the Swiss.
- `brackets[]`: `{index, matches[]}` where each match = `{players:[{loginid, player, seeding,
  wins, losses, winner}, ...]}`. **This is the ONLY real head-to-head (top-8 playoff) data.**
- All numeric fields are **strings** in the JSON (e.g. `"wins":"8"`) — cast when parsing.

### 2. ⚠️ THE FLAKY-PAYLOAD GOTCHA (most important)
The same URL sometimes returns a **FULL** payload (~355 KB, includes `decklists`) and sometimes
a **LITE** payload (~46 KB, has `standings`/`brackets`/`winloss` but **NO `decklists`**). This is
server-side node/cache variability — NOT deterministic by header (I tested; `Accept: */*` looked
correlated once but it's just flaky). Active community caches (Badaro, Jiliac forks) have ABANDONED
mtgo.com scraping over this — they only do melee.gg/CardsRealm now.

**SOLUTION — retry until `decklists` is non-empty:**
```python
def fetch_full(url, tries=8, ua="Mozilla/5.0"):
    for _ in range(tries):
        html = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": ua}), timeout=30
        ).read().decode("utf-8", "replace")
        m = re.search(r'window\.MTGO\.decklists\.data\s*=\s*(\{.*?\});', html, re.S)
        data = json.loads(m.group(1)) if m else {}
        if data.get("decklists"):
            return data
        time.sleep(1)
    raise RuntimeError("only got lite payload (no decklists) after retries")
```
Hit rate is decent (often full on the first try). `fetch.py` MUST implement this retry loop and
treat a lite payload as a soft failure to retry. Cache the FULL payload to `data/raw/<slug>.json`
so we never depend on the flaky endpoint twice.

### 3. Event ENUMERATION is unsolved (the remaining risk)
- `mtgo.com/decklists` index, `sitemap.xml`, `robots.txt`, `decklists/data/all-decklists.json`
  all **soft-404 to the SPA shell** — not usable for listing events.
- **Badaro/MTGODecklistCache is ARCHIVED** (stops ~mid-2025). Active forks **Jiliac/** and
  **brossignol/** are fresh (pushed July 2026) BUT only under `Tournaments/melee.gg`,
  `Tournaments/CardsRealm`, etc. — **`Tournaments/mtgo.com` stops at 2024 in all of them.**
  So there is NO current mtgo.com mirror to enumerate from.
- **Recommended path for `discover.py`:** since we can't enumerate mtgo.com's index, accept
  explicit event URLs/slugs via CLI (`--event-url`, or a `--slugs-file`) as the primary interface,
  AND implement a best-effort slug guesser from the known pattern (see below). Consider also
  scraping a lightweight third-party listing that just gives mtgo.com event SLUGS (not decklists)
  if one is found — but the fetch of actual data should stay on mtgo.com per the user's choice.
  Flag this to the user; it's the one place the plan's "primary discovery" assumption broke.

**Known slug pattern:** `<format>-<eventtype>-<n?>-<YYYY>-<MM>-<DD><eventid>`, e.g.
`modern-showcase-challenge-2026-07-1212847089`, `modern-challenge-64-2025-04-1712769870`.
Note the date and a trailing numeric event id are concatenated (`...07-12` + `12847089`).

### 4. Reference points
- Known-good event for testing: `modern-showcase-challenge-2026-07-1212847089` (this is the fixture).
- `mtg_parser` (lheyberger): parses decklists from OTHER sites; **redundant here** (MTGO JSON already
  structured). Inspiration only — don't add it as a dependency.

---

## Remaining design decisions already locked (from user Q&A)
1. Matchup data = **MTGO official + top-8 head-to-head matrix** (aggregated over many events).
   No Swiss matchup matrix (impossible — MTGO publishes no Swiss pairings).
2. Event scope = **Challenges + Premier/Qualifier** (full records+brackets) **+ League 5-0**
   (decklists only, metagame share only — leagues have no standings/winloss/brackets).
3. Archetype ID = **rule-based signature-card classifier**, `config/archetypes.json`
   (ordered rules: `{name, requires:[...], any_of:[...], excludes:[...]}`, first match wins,
   else `"Unknown"`). Match on `card_attributes.card_name`.
4. Storage = **raw JSON cache** (`data/raw/`) **+ processed CSVs** (`data/processed/`):
   `metagame.csv`, `records.csv`, `matchups.csv`, `standings.csv`, `decks.csv`.

## Coding standards (user requirement)
- **Modern strict-typed Python** targeting clean `uv run mypy mtgmodern` under `--strict`.
- Built-in generics (`list[str]`, `dict[str,int]`), `X | None`, `@dataclass(slots=True, frozen=True)`
  for records, `TypedDict` for the raw MTGO JSON shape, explicit return types everywhere,
  `Sequence`/`Mapping` for params. Narrow `Any` at the JSON boundary in `parse.py` (all raw fields
  are strings — cast there).
- Runtime = **stdlib only** (`urllib`, `json`, `csv`, `re`, `dataclasses`, `argparse`). Tests use
  stdlib **`unittest`** (so they run with zero installs). mypy/pytest are dev-only.

## How to run things
```bash
export PATH="$HOME/.local/bin:$PATH"
cd /home/ben/linux-code
uv run python --version              # 3.14.6
uv run mypy mtgmodern                # must stay clean under --strict
uv run python -m unittest discover -s tests
```

## Suggested next steps (build order)
1. **parse.py** — `TypedDict`s for raw JSON + frozen dataclasses (`Event, PlayerDeck, Standing,
   WinLoss, BracketMatch`) + `extract_event_data(html)->dict` (the regex) +
   `parse_event(raw)->Event`. Test against `challenge_event_small.json` (fast) and
   `challenge_event.json` (counts: 32/32/32, brackets present, cards non-empty, string→int casts).
2. archetype.py + config/archetypes.json (seed ~10 current Modern archetypes) + tests.
3. fetch.py (retry-until-decklists, disk cache) + storage.py (CSV writers) + tests
   (monkeypatch the network / feed a local fixture file).
4. discover.py (CLI event-url/slug input; document enumeration limitation) + analyze.py
   (metagame, records, top-8 matchup matrix; join bracket players' loginids→archetypes) + tests
   (synthetic brackets: winrate symmetry A vs B = 100%−B vs A, counts).
5. cli.py + run.py; smoke run: collect a couple events → analyze → eyeball CSVs.

## Verification checklist (from plan)
- `uv run mypy mtgmodern` clean; `uv run python -m unittest discover -s tests` green.
- `metagame.csv` shares ≈100%; `matchups.csv` A-vs-B winrate = 100%−B-vs-A; counts match brackets.
- Spot-check one archetype label against its actual decklist.
