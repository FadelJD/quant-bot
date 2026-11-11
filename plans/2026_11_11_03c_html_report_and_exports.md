# 03c · HTML report and exports

Created 2026-11-11 · Wave 3 · Parallel with 03a, 03b, 03d, 03e · Needs 02c, 02g · Spec section 16

## Goal

One self-contained HTML file per run, under 5 MB, readable offline on a phone, with the verdict
first. Plus a stable `metrics.json` and a report that can be regenerated from disk.

## Owns

`src/kestrel/reporting/html.py`, `reporting/export.py`, `reporting/templates/`.

## Current state

A Jinja2 template with three Plotly figures and a JSON export exist. The file is 5.11 MB (D01),
the `report` command cannot regenerate (D09), and output is not byte-stable (D24).

## Work items

1. **Size (D01).** Stop embedding the full plotly.js bundle. Options, in order of preference:
   a. `plotly.js-basic-dist-min` (about 1 MB; covers scatter, bar, and heatmap needs to be checked);
   b. a custom partial bundle committed under `reporting/templates/vendor/` with its licence;
   c. render charts as static inline SVG with a 200-line helper and drop plotly from the report.
   Pick the first that covers every chart, record the choice. Budget: report under 2 MB for the
   spec workload, hard limit 5 MB enforced in code (`render_report` raises above it).
2. **Sections, in the spec's order.** Verdict banner with reasons; headline metrics table; equity
   curve with drawdown shading; monthly returns heatmap; performance by regime; trade list
   (sortable with 30 lines of vanilla JS, capped at 1 000 rows with a note); parameter sensitivity
   heatmap; walk-forward table; Monte Carlo drawdown distribution; configuration dump; data
   manifest; provenance block (I7).
3. **No verdict, no numbers.** Spec: "a backtest number without a validation verdict is not
   shown". `kestrel backtest` output gets a grey banner "not validated" and the headline metrics
   are visibly marked provisional. Decide with 04a whether `backtest` should run quick validation
   by default; the recommended default is yes, with `--no-validate` to skip.
4. **Extra panels for the additions.** Cost stress (I2) as a two-row table; lookahead audit (I3)
   as pass or the first failing timestamp; trial count and its source (I1) next to the deflated
   Sharpe.
5. **Responsive.** Single column under 600 px; charts with `responsive: true`; tables scroll
   horizontally inside their own container. Check at 375 px with the preinstalled Playwright
   Chromium from a script and save `docs/img/report_mobile.png` and `docs/img/report_verdict.png`
   (the README needs the second one).
6. **No external requests.** No CDN, no web fonts, no remote images. Add a check that greps the
   output for `http://` and `https://` outside the config dump and the data manifest.
7. **Determinism (D24).** Render with a fixed `generated_at` taken from the result's provenance,
   stable ordering, fixed float formatting, and Plotly div ids set explicitly (Plotly generates
   random ids by default). Two renders of the same result must be byte-identical.
8. **Regeneration (D09).** `load_and_render(run_dir)` reads `BacktestResult.load`, the validation
   JSON if present, and writes `report.html`. `kestrel report --run-id` calls it.
9. **`metrics.json`.** `schema_version`, stable key names, sorted keys, NaN and infinity written
   as `null`, floats rounded to 12 significant digits so golden files compare within 1e-9.
   Document the schema in `docs/` (handoff note for 04c).
10. **Live report.** `render_live_report(store, run_id, ...)` builds the same report from the
    state store's equity and fills for the weekly Telegram send. It takes a store, not a runner,
    so `reporting/` does not import `live/`.
11. **Display time zone.** All timestamps shown in `display_tz` with the zone abbreviation;
    stored values stay UTC.
12. **Accessibility basics.** Verdict conveyed by text as well as colour; table headers with
    `scope`; sufficient contrast.

## Done when

- Report for the spec workload is under 2 MB, opens with the network disabled, and renders at
  375 px (screenshots committed).
- Two renders are byte-identical.
- `kestrel report --run-id` regenerates from disk with no re-run.
- D01, D09 closed; D24 report half closed. Static checks pass on owned files.

## Out of scope

A web dashboard or server. PDF export. Tests.
