# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Bruker Data Format

The ultimate source of truth for implementing this software is FILE_FORMAT.md

## Project Overview

pvraw is a Python library for accessing and converting raw MRI data from Bruker Biospin preclinical scanners. It provides a CLI (`pvraw`) and Python API for reading Bruker PvDatasets (directory or archive), deriving their geometry, and exporting to NIfTI/BIDS formats.

This began as a hard fork of the upstream [BrkRaw](https://github.com/BrkRaw/brkraw) 0.3.x/0.4 line and is developed independently of upstream 0.5+. The distribution and the import package are both `pvraw`. Current version: 1.0.0.

## Build & Development Commands

```bash
uv sync                       # Runtime deps only (editable install)
uv sync --extra dev           # Also install pytest/ruff/bids-validator (needed to run tests)

# Testing
uv run pytest                       # All tests (sample data auto-fetched from the network)
uv run pytest -m "not data"         # Only the offline unit tests (no downloads)
uv run pytest tests/08_orientation_test.py  # Run a single test file

# Linting
uv run ruff check .            # Config in pyproject.toml; must be clean
uv run ruff check . --fix      # Safe fixes only -- then run the tests, see below
```

CI installs from `uv.lock` (`uv sync --locked`), so every tool version is
pinned: a new ruff or pytest release cannot break an unrelated PR. `--locked`
also fails the build when `pyproject.toml` was edited without re-running
`uv lock`. Changing a tool version is therefore a deliberate lockfile commit,
not something that happens on its own.

## Architecture

**All Bruker file reading is delegated to `brukerapi`** — directory and archive
traversal, JCAMP-DX parsing, byte→array assembly, and the voxel-to-patient
affine (ADR 0002, as amended). Do not reintroduce any of them here. What this
project owns is how the subject was framed, NIfTI headers and BIDS. Problems in
what is delegated get fixed upstream.

### Data flow

```
PvDataset (directory or .zip/.PvDatasets archive)
  → BrukerLoader (lib/loader.py)      — entry point, also exposed as pvraw.load()
    → Study (api/data/study.py)       — scan_id → brukerapi Experiment; the vocabulary boundary
      → Scan (api/data/scan.py)       — reco_id → brukerapi Processing → brukerapi Dataset
        → ScanInfoAnalyzer            — derived values: image, slicepack, orientation, cycle
          → AffineAnalyzer            — brukerapi's affine + the subject correction
          → NIfTI/BIDS export         — via app/tonifti/
```

### Key layers

- **`pvraw/lib/`** — `BrukerLoader` (loader.py), the parameter accessor and
  BIDS/metadata helpers (utils.py), subject-orientation conventions
  (subject_orient.py), BIDS entity/filename rules (bids.py), BIDS metadata
  references (reference.py), custom exceptions (errors.py)
- **`pvraw/api/data/`** — `Study` and `Scan`: the only place that maps
  `scan_id`/`reco_id` onto `brukerapi`'s Experiment/Processing (see `CONTEXT.md`)
- **`pvraw/api/analyzer/`** — `ScanInfoAnalyzer` (parameters → derived
  values), `AffineAnalyzer` (takes `brukerapi`'s affine and applies the
  subject-type/position correction — ADR 0001 as amended)
- **`pvraw/api/helper/`** — the derivations themselves: image, slicepack,
  orientation (subject type/position only), cycle, diffusion, protocol,
  dataarray, plus `axis_labels`/`frame_groups`, which name the axes of an
  assembled image
- **`pvraw/app/tonifti/`** — NIfTI assembly and headers: `StudyToNifti`,
  `ScanToNifti`, `Header`, `ToNiftiPlugin`
- **`pvraw/scripts/`** — CLI entry points (`pvraw.py` with subcommands: info, tonii, tonii_all, bids_helper, bids_convert)

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
`14_slice_distance`, `15_pv_version`, `16_parameter_value`, `17_tabular`,
`18_derived`, `19_asl`, `20_cli`, `20_sweep_tools`, `21_archive`. Data-dependent tests are marked `data` and fetch
public sample data from the network (Zenodo / GitHub), cached under
`$PVRAW_TEST_DATA_DIR`; `pytest -m "not data"` runs only the offline unit
tests. CI runs the unit suite on Python 3.11–3.14 across Ubuntu/Windows/macOS
and the `data` suite once on Ubuntu.

Geometry is verified by comparison against data, not against recorded output.
`tools/sweep_nifti.py` records the affine, a data hash, the shape and the header
fields for every reconstruction under a tree, and `--compare=<earlier.json>`
diffs two runs -- run it before and after any change that could move geometry.
Correctness itself comes from acquisitions of the same object that must agree:
see `EXPERIMENT_PLAN.md`.

## Linting

Ruff, configured in `pyproject.toml` under `[tool.ruff.lint]`.

The rule set is ruff's defaults minus what this project deliberately does not
follow, so a finding is a real one rather than noise. Each exemption is
recorded with its reason next to the config; the short version:

- **`BLE001`** (blind `except Exception`) is off project-wide. Converting a
  study must not abort because one scan of it fails, so the per-scan loops and
  the optional-parameter fallbacks catch broadly on purpose -- each one warns,
  falls back to a documented default, or re-raises a typed error.
- **`N999`/`S112`** are off for `tests/`, whose modules are named for the layer
  they cover (`02_api_analyzer`, `04_api_data`, ...).

Prefer the project's own exceptions from `lib/errors.py` (`InvalidValueInField`
for a bad field value, `InvalidApproach` for a bad call) over bare
`raise Exception(...)`, so callers can catch by type. Note that
`UnexpectedError` and `InvalidApproach` print a traceback on construction,
which emits a bare `NoneType: None` when raised outside an `except` block.

### `ruff --fix` is not safe unattended here

Run the tests after any `--fix`, and never take `--unsafe-fixes` without
reading the diff. The canonical example: `brukerapi`'s containers used to
define `__getitem__` without `__iter__`, so when `SIM118` rewrote
`for k in pars.keys()` to `for k in pars` it broke 21 tests -- bare iteration
fell back to `__getitem__(0)` and raised `KeyError` against a name-keyed
store. Fixed upstream over #184 (`JCAMPDX`, 0.4.4) and #187/#188
(`Folder`/`Dataset` and their subclasses, 0.4.5), which is why the floor is
`>=0.4.5`: every container is now genuinely iterable and the hazard is gone,
but a lint rewrite can surface exactly this class of look-alike API anywhere.

Because `--fix` rewrites in bulk, verify behaviour rather than assuming: run
`uv run pytest`, and for anything touching geometry or sidecars use
`tools/sweep_nifti.py --compare` (see Testing above), which pins every affine
and data hash and is what proves a lint sweep changed nothing.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`gdevenyi/pvraw`), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical default labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
