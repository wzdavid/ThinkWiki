# Changelog

## v1.7.3
### Changed
- Removed legacy env var compatibility (`MINIMAX_*`, `SILICONFLOW_API_KEY`, `BGE_ENDPOINTS`). Only `THINKWIKI_LLM_*` and `THINKWIKI_EMBED_*` are accepted.

## v1.7.2
### Security
- Added SSRF protections for user-supplied URL fetches in `ingest.py` and `clip.py` via `url_safety.py` (scheme allowlist, private/metadata IP blocking, redirect validation). Set `THINKWIKI_ALLOW_PRIVATE_URL_FETCH=1` only for local testing if you intentionally need loopback fetches.
- `serve` now refuses non-loopback `--host` values unless `--allow-lan` is passed explicitly.
- Upgraded `cryptography` from `48.0.0` to `48.0.1` (GHSA-537c-gmf6-5ccf).

### Changed
- Replaced MiniMax-specific `m27_client.py` with provider-neutral `llm_client.py` using OpenAI-compatible chat completions. LLM features stay disabled unless `THINKWIKI_LLM_API_KEY`, `THINKWIKI_LLM_BASE_URL`, and `THINKWIKI_LLM_MODEL` are all set.
- Replaced `bge_client.py` with `embed_client.py` and unified env vars: `THINKWIKI_EMBED_API_KEY` (required to enable), `THINKWIKI_EMBED_BASE_URL` (defaults to SiliconFlow), `THINKWIKI_EMBED_MODEL` (defaults to `BAAI/bge-m3`).
- Added `ai_config.py` as the single source of truth for optional remote AI configuration.
- `crystallize`, `digest`, and entity merge now print explicit notices before sending content to configured remote APIs.
- Deprecated legacy env vars (`MINIMAX_*`, `SILICONFLOW_API_KEY`, `BGE_ENDPOINTS`) with stderr warnings; they remained supported until v1.7.3.

## v1.7.1
### Security
- **Removed unauthorized hardcoded BGE embedding endpoints and default API key from `bge_client.py`.** v1.7.0 had shipped with private HTTP endpoints and a baked-in shared key that did not match the documented `SILICONFLOW_API_KEY` flow. Embedding now uses SiliconFlow (`https://api.siliconflow.cn/v1/embeddings`) and requires an explicit `SILICONFLOW_API_KEY`; there is no default key and no silent third-party fallback.
- `bge_embed` now fails fast when `SILICONFLOW_API_KEY` is unset, matching `utils.py` and the README/SKILL documentation.

## v1.7.0
### Added
- Added `scripts/m27_client.py` — MiniMax M2.7 HTTP client with retry, backoff, 4xx short-circuit, and degraded fallback, shared by `crystallize` and `digest`.
- Added `scripts/bge_client.py` — BGE-M3 embedding client (SiliconFlow `BAAI/bge-m3`, OpenAI-style `/v1/embeddings`) for semantic entity matching, with multi-endpoint failover and explicit auth-error handling.
- Added BGE-M3 embedding branch to `ambiguous_entity_merge_candidates` in `utils.py` so entity alias groups can be detected by semantic similarity in addition to string matching. Configured via `SILICONFLOW_API_KEY` (optional; degrades gracefully).
- Added `MINIMAX_API_KEY` and `SILICONFLOW_API_KEY` environment variable documentation across `SKILL.md`, `README.md`, and `README.zh.md`.

### Changed
- Replaced ~500 lines of heuristic content generation in `crystallize.py` with `m27_crystallize()` calls, and ~350 lines in `digest.py` with `m27_digest()` calls, removing dead constants and helper functions.
- Updated `_post_json` in `bge_client.py` to accept an explicit `api_key` parameter, send `User-Agent: ThinkWiki/1.0`, and short-circuit on 401/403 auth failures instead of retrying.
- Updated `_resolve_api_key` call site to the `bge_embed` entry point so key resolution happens once per batch, not per request.
- Updated `bge_embed` docstring with worst-case latency formula and 4xx short-circuit behavior.
- Updated `m27_crystallize` and `m27_digest` fallback messages to defend against empty titles.

### Fixed
- Fixed `bge_client` 401/403 handling: auth failures now raise `BgeServiceUnavailable` immediately instead of silently cycling through endpoints.
- Fixed `m27_client` fallback stderr warning to handle `None` title gracefully.
- Fixed `m27_client` `_parse_result` to strip `thinking` tags before JSON parsing, preventing unnecessary heuristic fallback on reasoning model output.
- Fixed `utils.py` BGE embedding branch: exceptions now log warnings to stderr instead of silently passing.

## v1.6.0
### Added
- Added a schema v2 content knowledge graph with `default_view = knowledge`, including page-backed nodes, extracted `claim` nodes, and semantic relations such as `about`, `belongs_to`, `depends_on`, `asserts`, `supports`, `contradicts`, and `suggests_related_to`.
- Added entity governance to the knowledge graph so page-backed entity nodes now carry aliases, can surface ambiguous identity collisions, and participate in deterministic merge review workflows.
- Added an `entity-merge-review` command that writes `output/graph/entity-merge-review.{json,md,html}` for manual review of ambiguous entity alias groups.
- Added `entity-merge-apply` so users can canonicalize one entity page, convert the rest into merged stubs, and rebuild downstream viewer / graph / governance outputs in one deterministic step.
- Added `entity-merge-apply --dry-run` so users can generate `output/graph/entity-merge-plan.{json,md,html}` before writing any entity pages.
- Added a `serve` command that exposes `<wiki-root>/output/` over loopback HTTP (default `http://127.0.0.1:8765/`) so agent hosts can browse inbox, viewer, graph, and governance pages in a browser.
- Added `README.zh.md` as the Chinese project overview alongside the English README.

### Changed
- Updated HTML workbench outputs (`output/index.html`, inbox, viewer, graph, and governance pages) to English so repository-facing previews and agent-host browsing stay consistent.
- Refreshed demo wiki outputs and README screenshot assets to match the current English HTML workspace.
- Rewrote `README.md` and `SKILL.md` around Agent Skills installation and conversational usage, including supported agent hosts and the recommended `serve` workflow for browsing HTML outputs.
- Updated `graph-report`, `status`, `health`, and `output/index.html` so entity counts, alias counts, ambiguous alias groups, and ambiguous entity counts are surfaced across terminal summaries and HTML workbench outputs.
- Updated graph construction and ingest so merged entity stubs continue to resolve old titles and aliases to the canonical entity page without polluting the active knowledge graph.
- Updated the output home so `entity-merge-review.html` and `entity-merge-plan.html` are treated as first-class governance artifacts alongside the graph report.

## v1.5.1
### Changed
- Updated `graph-report` terminal output to stay ASCII-safe across platforms, preventing Windows CI failures caused by console encoding when the report summary contains non-ASCII text.

## v1.5.0
### Added
- Added a deterministic `health` command so users can check workspace structure, inbox consistency, and stale outputs without invoking heavier content workflows.
- Added a compact `status` command so users can quickly inspect page counts, inbox readiness, and the current viewer/graph/inbox output state from the terminal.
- Added a `batch-clip` command so users can collect a whole directory or a manifest of `source / url / text` items into the inbox in one run.
- Added a `batch-ingest` command so users can promote `ready` inbox items into the wiki in batches, with `--dry-run`, `--limit`, and quality-based filtering.
- Added a deterministic `graph-report` command so users can turn the current graph into a governance report with isolated pages, hub stubs, fragile bridges, isolated clusters, and top graph fixes.

### Changed
- Updated `output/inbox/index.html` so the `Ready To Ingest` section now recommends `batch-ingest` dry-run and execution commands before the per-item ingest commands.
- Updated `status`, `health`, and `output/index.html` so the new graph governance report is surfaced in terminal summaries and the HTML workspace home.
- Updated `graph-report` to also write `output/graph/report.html`, making the governance report directly browsable like the rest of ThinkWiki outputs.
- Updated demo generation and committed demo outputs so repository-facing pages no longer expose local absolute paths, and removed internal competitive research notes from `docs/`.

## v1.4.0
### Added
- Added structured sidecar metadata for web clips in `normalized/inbox/*.json`, including adapter, site name, author, publish date, and source URL.
- Added explicit `clip --adapter auto|wechat|generic` selection so the inbox capture flow can evolve toward adapter-based web extraction.
- Added inbox extraction quality states (`ready`, `review`, `weak`) so the review page can highlight which clips are safe to ingest and which still need manual checking.
- Added `clip --mode auto|wait` so webpage capture can retry for a short window before writing inbox artifacts, and record whether the wait completed or timed out.
- Added `clip --media ask|always|never` so webpage images can stay remote, be marked for later review, or be localized into `normalized/assets/inbox/...` during capture.
- Added structured capture reasons such as `loading_placeholder`, `body_too_short`, and `metadata_sparse`, so inbox review can explain why a web clip still needs attention.

### Changed
- Updated `output/inbox/index.html` and the workspace inbox cards so clipped webpages now surface adapter, source, author, publish date, and metadata links during review.
- Updated the WeChat extraction path so common embedded code blocks are normalized before Markdown conversion, making technical articles easier to preserve.
- Updated `output/inbox/index.html` into a grouped review console with `Ready To Ingest`, `Needs Review`, and `Weak Captures` sections, plus priority commands for the next ingest steps.
- Updated `output/index.html` so the workspace home now highlights ready inbox items first and links directly to the ready review section.

## v1.3.0
### Added
- Added a new `clip` command and `inbox` storage flow so webpages, pasted text, and local files can be collected first and ingested into the wiki later.
- Added an `output/inbox/index.html` review page so users can browse pending inbox items and copy the next `ingest` command without leaving the browser.

### Changed
- Updated `output/index.html` so the workspace home now shows an `Inbox Queue`, inbox counts, clip-driven next actions, and a direct entry to the inbox review page.
- Updated `clip` so it backfills missing `raw/inbox` and `normalized/inbox` directories for older wikis, regenerates `output/inbox/index.html`, and refreshes the output home after each capture.

## v1.2.0
### Added
- Added a workspace-style `output/index.html` home that surfaces `What Changed`, `Next Actions`, `Needs Attention`, `Graph Snapshot`, and `Featured Pages`.
- Added homepage recommendations that reuse graph insight data so users can move from the output hub into the right next action faster.

## v1.1.0
### Added
- Added `Graph Insights` to `output/graph/index.html` so the graph page now surfaces key pages, bridge pages, weakly connected pages, and suggested links.
- Added structured graph insight data to `output/graph/graph.json` and `output/graph/graph.md` for downstream analysis and richer summaries.
- Added graph-side interactions for insight-driven exploration, including clickable insight cards and suggested-link highlighting in the SVG graph.

### Changed
- Updated the graph explorer README copy and demo screenshot so the new insight panel is visible in the repository front page.

## v1.0.1
### Fixed
- Fixed GitHub Actions regression tests so spawned test scripts now prefer the repository runtime in `.venv` after `bootstrap`, instead of falling back to the system Python.
- Fixed CI failures in `ingest.py` regression coverage caused by running document and directory ingest tests outside the bootstrapped ThinkWiki runtime.

## v1.0.0
### Released as ThinkWiki
- First standalone release under the `ThinkWiki` brand.
- Removed the legacy `scripts/llm-wiki` compatibility entry and standardized on `scripts/thinkwiki`.
- Standardized runtime environment variables on `THINKWIKI_*`.
- Renamed the regression test suite to `tests/test_thinkwiki.py`.
- Refreshed demo outputs, page titles, and repository-facing docs to consistently use `ThinkWiki`.

### Added
- Added an offline graph viewer at `output/graph/index.html` so graph generation now produces a directly browsable HTML artifact.
- Added richer graph node metadata including summary, confidence, status, updated date, path, and sources.
- Added a shared `output/index.html` hub so users can open the graph page and viewer page from one place.
- Added repository-hosted PNG screenshots for the viewer page and graph page so README can show real product output immediately.
- Added a repository-hosted PNG screenshot for `output/index.html` so README now shows the entry hub alongside viewer and graph pages.
- Added a reusable `scripts/build_demo_wiki.py` script to regenerate the demo wiki behind the README screenshots.
- Added release notes tracking for `ThinkWiki`.

### Changed
- Updated `README.md` to better explain the single-skill installation model, quick start flow, and viewer/graph outputs.
- Updated `SKILL.md` to treat graph and viewer tasks as HTML-first deliverables instead of raw data outputs.
- Updated graph layout generation to use a denser, degree-aware column layout and auto-center selected nodes in the graph stage.
- Updated graph edge rendering so `references`, `links_to`, `includes`, and `cites` now use distinct colors and line styles.
- Updated graph exploration so users can switch between `1-hop`, `2-hop`, and full-graph visibility around the selected node.
- Updated graph exploration so users can toggle individual edge types on and off when reading dense relationship maps.
- Updated graph exploration so users can jump to `all`, `concept`, `decision`, and `source` views with one-click focus presets.
- Updated graph node details so the side panel now summarizes per-edge-type relationship counts for the selected node.
- Updated graph and viewer pages so they can jump to each other through URL hashes and printed file URIs.
- Updated `ask`, `query`, `digest`, and `crystallize` so they mention the shared `output/index.html` hub whenever viewer or graph outputs already exist.
- Updated `output/index.html` so it now acts like a lightweight product homepage with wiki title, generated date, page count, node count, edge count, recent pages, featured concept/decision pages, and a recommended next step.

### Fixed
- Kept wiki-backed graph nodes from losing their richer metadata when placeholder nodes are merged during graph construction.
