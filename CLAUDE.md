# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BrkRaw-legacy is a Python library for accessing and converting raw MRI data from Bruker Biospin preclinical scanners. It provides a CLI (`brkraw-legacy`) and Python API for reading Bruker PvDatasets (directory or archive), deriving their geometry, and exporting to NIfTI/BIDS formats.

This is a hard fork of the upstream [BrkRaw](https://github.com/BrkRaw/brkraw) 0.3.x/0.4 line, developed independently of upstream 0.5+. The distribution is `brkraw-legacy`, the import package is `brkraw_legacy`. Current version: 0.5.0.

## Build & Development Commands

```bash
uv sync                       # Runtime deps only (editable install)
uv sync --extra dev           # Also install pytest/ruff/bids-validator (needed to run tests)

# Testing
uv run pytest                       # All tests (sample data auto-fetched from the network)
uv run pytest -m "not data"         # Only the offline unit tests (no downloads)
uv run pytest tests/08_orientation_test.py  # Run a single test file

# Linting
uv run ruff check .            # Uses ruff defaults
```

## Architecture

**All Bruker file reading is delegated to `brukerapi`** — directory and archive
traversal, JCAMP-DX parsing, byte→array assembly, and the voxel-to-patient
affine (ADR 0002, as amended). Do not reintroduce any of them here. What this
project owns is how the subject was framed, NIfTI headers and BIDS. Problems in
what is delegated get fixed upstream.

### Data flow

```
PvDataset (directory or .zip/.PvDatasets archive)
  → BrukerLoader (lib/loader.py)      — entry point, also exposed as brkraw_legacy.load()
    → Study (api/data/study.py)       — scan_id → brukerapi Experiment; the vocabulary boundary
      → Scan (api/data/scan.py)       — reco_id → brukerapi Processing → brukerapi Dataset
        → ScanInfoAnalyzer            — derived values: image, slicepack, orientation, cycle
          → AffineAnalyzer            — brukerapi's affine + the subject correction
          → NIfTI/BIDS export         — via app/tonifti/
```

### Key layers

- **`brkraw_legacy/lib/`** — `BrukerLoader` (loader.py), the parameter accessor and
  BIDS/metadata helpers (utils.py), subject-orientation conventions
  (subject_orient.py), BIDS entity/filename rules (bids.py), BIDS metadata
  references (reference.py), custom exceptions (errors.py)
- **`brkraw_legacy/api/data/`** — `Study` and `Scan`: the only place that maps
  `scan_id`/`reco_id` onto `brukerapi`'s Experiment/Processing (see `CONTEXT.md`)
- **`brkraw_legacy/api/analyzer/`** — `ScanInfoAnalyzer` (parameters → derived
  values), `AffineAnalyzer` (takes `brukerapi`'s affine and applies the
  subject-type/position correction — ADR 0001 as amended)
- **`brkraw_legacy/api/helper/`** — the derivations themselves: image, slicepack,
  orientation (subject type/position only), cycle, diffusion, protocol,
  dataarray, plus `axis_labels`/`frame_groups`, which name the axes of an
  assembled image
- **`brkraw_legacy/app/tonifti/`** — NIfTI assembly and headers: `StudyToNifti`,
  `ScanToNifti`, `Header`, `ToNiftiPlugin`
- **`brkraw_legacy/scripts/`** — CLI entry points (`brkraw_legacy.py` with subcommands: info, tonii, tonii_all, bids_helper, bids_convert)

### Reading parameters

Never call `brukerapi`'s accessors directly. `lib.utils.get_value(parameters,
key, default)` resolves the JCAMP-DX representation (`<...>` quoting, numeric
literals, struct arrays as rows) and defaults an absent key — absence is
ParaVision-version dependent, so an unguarded read fails as "works on PV6,
crashes on PV5.1".

### External dependencies of note

- **brukerapi** — all Bruker file reading (ADR 0002). Fix problems upstream
  rather than working around them here
- **xnippet** (PyPI) — configuration management framework, used for `XnippetManager` in `__init__.py`
- **reshipe** — recipe parser, used for the study header in `api/data/study.py`
- **nibabel** — NIfTI format support (required, used in orientation math and conversion)
- **bidsschematools** — BIDS entity/datatype definitions, used by `lib/bids.py`

## Testing

Tests are numbered by layer: `02_api_analyzer`, `04_api_data`, `05_app_tonifti`,
`06_bids`, `07_conversion`, `08_orientation`, `09_nifti_header`,
`10_bids_metadata`, `11_diffusion`, `12_complex_warning`, `13_slice_axis`,
`14_slice_distance`, `15_pv_version`. Data-dependent tests are marked `data` and fetch
public sample data from the network (Zenodo / GitHub), cached under
`$BRKRAW_TEST_DATA_DIR`; `pytest -m "not data"` runs only the offline unit
tests. CI runs the unit suite on Python 3.11–3.14 across Ubuntu/Windows/macOS
and the `data` suite once on Ubuntu.

Geometry is verified by comparison against data, not against recorded output.
`tools/sweep_nifti.py` records the affine, a data hash, the shape and the header
fields for every reconstruction under a tree, and `--compare=<earlier.json>`
diffs two runs -- run it before and after any change that could move geometry.
Correctness itself comes from acquisitions of the same object that must agree:
see `EXPERIMENT_PLAN.md`.

## Linting

Ruff for linting. Type checking config in `mypy.ini`.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`gdevenyi/brkraw-legacy`), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical default labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
