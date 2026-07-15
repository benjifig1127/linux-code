# Plan: MTGO Modern metagame & matchup analysis tool

## Context
User plays competitive Modern and wants a Python program that scrapes online MTGO results
for the main decks, caches them locally, and analyzes win/loss records for the top matchups.
Source: official mtgo.com results. Reference: lheyberger/mtg_parser (inspiration only).

Everything is built inside `/home/ben/linux-code` (currently an empty dotfiles repo).

## Key research findings (verified against live data)
- Python 3.12 present; `pip` NOT installed but `venv` works (venv ships pip). Build in a `.venv`.
- mtgo.com event pages are JS-rendered but embed a JSON blob in HTML: `window.MTGO.decklists.data`.
  **Verified fields**: `decklists` (per-player main/sideboard w/ card attributes), `standings`
  (rank, score, OMW%/GW%/OGW%, eliminated), `winloss` (per-player aggregate match wins/losses),
  `brackets` (top-8 playoff = REAL head-to-head A-vs-B match results), `final_rank`, `format`,
  `player_count`, `starttime`, `event_id`.
- **Hard constraint**: MTGO publishes NO Swiss pairings. Who-played-whom is unknown in Swiss.
  A true full matchup matrix is impossible from MTGO alone. Only `brackets` (top-8) gives real
  head-to-head, meaningful only aggregated across many events. (User accepted this: option
  "MTGO official + top-8 head-to-head".)
- `mtg_parser` parses decklists from OTHER sites (Moxfield/Aetherhub/…); redundant here because
  MTGO JSON already has structured card lists. Used as design inspiration only.
- Event ENUMERATION: mtgo.com index/sitemap/candidate feeds all soft-404 to the SPA shell — not
  usable. Resolved discovery strategy below.

## User decisions (from clarifying questions)
1. Matchup data: **MTGO official + top-8 head-to-head matrix** (aggregated across events).
2. Event scope: **Challenges + Premier/Qualifier** (full JSON: records + brackets) **and League
   5-0** (decklists only, no records — used for metagame share only).
3. Archetype ID: **rule-based signature-card classifier** (editable JSON config).
4. Storage: **raw JSON cache + processed CSVs**.

## Python toolchain, upgrade & typing (added per user request)
- Current: system Python 3.12.3 on Ubuntu 24.04 (WSL), no pip/pyenv/uv. **Do NOT upgrade system
  Python** — WSL/OS tooling depends on it.
- Install **uv** (per-user `curl -LsSf https://astral.sh/uv/install.sh | sh`). uv (a) installs the
  **newest stable CPython** as a standalone build with zero system risk, (b) manages the project
  venv, (c) provides pip — fixing the missing-pip problem.
- `uv python install 3.14` (newest stable as of 2026-07; pin whatever `uv python list` reports as
  latest stable). Create the project venv on it: `uv venv --python 3.14`. Record the exact version
  in `.python-version` and README.
- **mypy strict**: `uv pip install mypy pytest`. Add `[tool.mypy] strict = true` in `pyproject.toml`
  plus `python_version` and `warn_unused_ignores`. Ship `mtgmodern/py.typed`. CI-style check:
  `uv run mypy mtgmodern`.
- **Modern typed style throughout**: built-in generics (`list[str]`, `dict[str, int]`), `X | None`
  unions, `@dataclass(slots=True, frozen=True)` for records, `TypedDict` for the raw MTGO JSON shape,
  `typing.Final`, explicit return types on every function, `Sequence`/`Mapping` for params. Target
  clean `mypy --strict` (no `Any` leaks; narrow at the JSON boundary in `parse.py`).

## Architecture (all under `/home/ben/linux-code`)
Runtime is stdlib-only (`urllib`, `json`, `csv`, `re`, `dataclasses`, `argparse`) — no third-party
runtime deps. Dev-only deps (mypy, pytest) live in the uv-managed venv. `pandas` optional, never
required. Tests use stdlib `unittest`.

```
linux-code/
  mtgmodern/
    __init__.py
    fetch.py        # urllib GET w/ UA header, retry/backoff, on-disk raw cache (never re-fetch)
    discover.py     # enumerate event URLs (see strategy below)
    parse.py        # extract window.MTGO.decklists.data via regex -> typed dataclasses
                    #   Event, PlayerDeck, Standing, WinLoss, BracketMatch
    archetype.py    # rule-based classifier; loads config/archetypes.json (signature cards)
    analyze.py      # metagame share, per-archetype aggregate W/L & avg finish & top-8 conversion,
                    #   top-8 head-to-head matchup matrix (archetype A vs B W/L, symmetric)
    storage.py      # write/read data/raw/*.json cache; write data/processed/*.csv
    cli.py          # argparse: `collect` (fetch+cache), `analyze` (build CSVs)
  config/
    archetypes.json # ordered signature-card rules; falls back to "Unknown"
  data/
    raw/            # one cached JSON per event (gitignored)
    processed/      # decks.csv, standings.csv, matchups.csv, metagame.csv
  tests/
    fixtures/       # 1-2 saved real event JSON blobs (small, checked in) for offline tests
    test_parse.py test_archetype.py test_analyze.py test_storage.py
  pyproject.toml  # project metadata + [tool.mypy] strict, dev deps (mypy, pytest)
  .python-version # pinned newest-stable version installed via uv
  README.md
  PLAN.md         # this plan, copied into the repo so the user can save it (per request)
  .gitignore      # add data/raw/, .venv/
  run.py          # thin entry -> mtgmodern.cli
```

### Event discovery strategy (the one implementation risk)
Primary: **Badaro/MTGODecklistCache** GitHub repo mirrors the *identical* mtgo.com event JSON,
in dated folders — trivially enumerable via the GitHub API (list `Tournaments/mtgo.com/<YYYY>/<MM>`,
filter filenames containing `modern`). This gives a reliable event list AND is still verbatim
official MTGO data. Fetch each event's canonical JSON from **mtgo.com** first (freshest); fall
back to the cached copy if the live page fails. Fully offline-friendly for backfill.
Fallback if that repo is unavailable: accept explicit event-slug/URL list via CLI (`--event-url`)
so the tool is always usable; document the slug format.

### Archetype classifier (config/archetypes.json)
Ordered list of rules; each rule = {name, requires: [cards all present], any_of: [...], excludes: [...]}.
First match wins; else "Unknown". Seed with ~10 current top Modern archetypes (e.g. Ragavan/Murktide,
Amulet Titan, Living End, Yawgmoth, Domain Zoo, Rhinos/Crashing Footfalls, Boros/Mono-W Energy, Hammer,
Tron, Burn) using distinctive signature cards. Config is data, not code — easy for user to tune.

### Analysis outputs (data/processed/*.csv)
- `metagame.csv`: archetype, count, meta_share%, avg_finish, top8_count, top8_conversion%.
- `records.csv`: archetype, match_wins, match_losses, match_winrate% (from `winloss`, Challenges/Premier only).
- `matchups.csv`: archetype_a, archetype_b, a_wins, a_losses, a_winrate%, n_matches — built from
  top-8 `brackets` across all collected events (each bracket match → both decks' archetypes joined
  by loginid). Sparse by nature; grows as more events are collected.
- `standings.csv` / `decks.csv`: tidy per-player rows for ad-hoc analysis.

## Build order (each step verified before moving on)
0. Install uv; `uv python install` newest stable (3.14); `uv venv`; `uv pip install mypy pytest`.
   Copy this plan to `linux-code/PLAN.md`. Write `pyproject.toml` (strict mypy) + `.python-version`.
1. Scaffold package + `.gitignore`; commit nothing until user asks.
2. `parse.py` + `test_parse.py` against a checked-in fixture (already have a real blob) — green first.
3. `archetype.py` + `test_archetype.py` (fixture decks → expected labels).
4. `fetch.py` + `storage.py` (cache) + tests using a local file:// or monkeypatched fetch.
5. `discover.py` (GitHub-API enumeration) + `analyze.py` + `test_analyze.py` (matchup matrix math
   on synthetic brackets: symmetry, winrate, counts).
6. `cli.py` + `run.py`; end-to-end smoke run collecting a handful of recent Modern events.

## Verification
- `uv run python --version` reports the newest stable (3.14.x).
- `uv run mypy mtgmodern` — clean under `--strict` (no errors).
- `uv run python -m unittest discover -s tests` — all green (offline, fixture-based).
- `python3 run.py collect --format modern --limit 5` → populates `data/raw/*.json`.
- `python3 run.py analyze` → writes `data/processed/*.csv`; eyeball `metagame.csv` (shares sum ~100%)
  and `matchups.csv` (A-vs-B winrate = 100% − B-vs-A winrate; counts match bracket totals).
- Manual spot-check one archetype label against the actual decklist.

## Notes / non-goals
- No Swiss matchup matrix (impossible from MTGO); matchups are top-8 only, by design.
- No third-party matchup-% scraping (user chose MTGO-only).
- Respectful scraping: cache-first, single UA, small delays; read-only public data.
