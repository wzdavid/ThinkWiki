# Changelog

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
