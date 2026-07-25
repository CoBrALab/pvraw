# ADR 0002: Delegate all Bruker file reading to `brukerapi`

- Status: Accepted (implemented in 0.5.0)
- Date: 2026-07-23 (implementation notes added 2026-07-24)

## Context

brkraw-legacy owns roughly 1,900 lines that read Bruker data and nothing else:

- **Two** parallel traversal stacks — `lib/pvobj.py` (`PvDatasetDir`/`PvDatasetZip`,
  reached only by `BrukerLoader`) and `api/pvobj/` (`PvStudy`/`PvScan`/`PvReco`/
  `PvFiles`, reached only by `app.tonifti` and `api.data`).
- One JCAMP-DX parser (`lib/utils.load_param` + `convert_*`), fronted by
  `api/pvobj/parameters.py`.
- Binary assembly: `api/analyzer/dataarray.py`, `api/helper/frame_group.py`,
  `api/helper/slicepack.py`, and the slope/reshape block in
  `BrukerLoader.get_dataobj`.

None of it is what the project is *for*. The differentiated value is geometry
(ADR 0001), NIfTI headers, and BIDS. The reading layer is undifferentiated
plumbing that has cost real correctness — most recently a JCAMP-DX tokeniser
that mis-parsed `<...>` struct-array comments containing parentheses, corrupting
`VisuFGOrderDesc` and breaking every derived (FG_ISA/DTI) reconstruction on the
`app.tonifti` path.

[`brukerapi`](https://github.com/isi-nmr/brukerapi-python) (MIT, `numpy` +
`pyyaml`) does exactly this layer and nothing else: JCAMP-DX parsing with typed
parameters, study/experiment/processing traversal, and schema-driven binary
assembly with slope/offset scaling, disk slice order, complex frames, and
frame-group reshaping. It is tested against PV 5.1, 6.0.1, 7.0.0 and PV360 3.x —
the same span as `resources/`. Its derived properties stop exactly where ours
begin: it computes `dim_type`, `shape_*`, `slope`, `offset`, `numpy_dtype`,
`num_slice_packages`; it computes no geometry at all.

The blocker was that `brukerapi` is path-only — every entry point is
`Path(path)` → `open()`/`np.memmap`, with zero `zipfile` support — while
`.zip`/`.PvDatasets` archives are a headline brkraw-legacy feature.

## Decision

**brukerapi owns shape, dtype and scaling. brkraw-legacy owns geometry, subject
framing and BIDS.** All file reading is delegated; `api/pvobj/` and
`lib/pvobj.py` are deleted outright.

- **Archives are fixed upstream, not shimmed.** `brukerapi` gains a duck-typed
  path protocol — it stops calling `os.*` directly and accepts anything
  implementing the pathlib read protocol, so callers pass
  `zipfile.Path(ZipFile(archive))`. This is ~50 lines across ~8 call sites
  (`os.listdir`→`iterdir`, a size helper for three `.stat().st_size` sites,
  `.with_suffix()` avoidance, a `memmap`-or-`frombuffer` fallback, and a
  `Path()` coercion guard) and adds no dependency. The same PR adds
  `get_value(key, default=None)`.
- **No adapter layer.** Consumers speak `brukerapi` types directly. This is a
  breaking change: `study.pvobj` becomes a `brukerapi` `Study`, and 0.5.0 is a
  major-version break with a rewritten README Python API section.
- **Named axes, not a collapsed frame axis.** Image assembly takes
  `dataset.data` with one axis per Frame Group and the affine/NIfTI/BIDS layers
  are rewritten against `dim_type`, rather than collapsing to `(x, y, z, frames)`
  and reverse-engineering frame groups downstream.
- **`PvFiles` is dropped.** The loose `2dseq` + `visu_pars` pair had one
  construction site, no tests and no documentation; standalone scan and reco
  *directories* are covered natively.
- **Vocabulary does not follow the dependency.** The CLI, README and Python API
  keep `scan_id`/`reco_id`; `exp_id`/`proc_id` appears at one call site. See
  `CONTEXT.md`.
- **`brukerapi>=0.4.1`**, floor only. Not `>=0.4`: 0.4.0 applies
  `RECO_transposition`, which the reconstruction has already applied, and
  silently transposes 73% of reconstructions. Reported as
  isi-nmr/brukerapi-python#153 and #154, removed upstream, released as 0.4.1.
  See `EXPERIMENT_PLAN.md`.

Verification is exact golden values — affine at full float64 precision, a
sha256 of the dataobj, shape and header fields — captured by `tools/sweep_nifti.py`
for one study per ParaVision generation plus the awkward cases (DTI maps, FG_ISA
derived recons, multi-echo, fieldmaps), with a full-corpus sweep once before
merge. Both implementations compute `d*slope + offset` in float64, so voxel
values are expected to match bit-for-bit once axes are reordered; anything that
differs is a semantic change to be explained, not float noise.

## Considered options

- **Extract archives to a temp directory.** ~40 lines we own instead of ~50
  upstream, but archives stay second-class and large ones cost disk and time on
  metadata-only commands. Rejected: upstreaming makes `brukerapi` structurally
  archive-capable rather than zip-special-cased, and we already have merged PRs
  there.
- **A thin adapter preserving `PvStudy`/`PvScan`/`Parameter`.** Lowest risk and
  absorbs upstream 0.x churn in one file, but retains ~528 lines of shells —
  roughly half the prize — for a project whose entire goal here is deletion.
- **Parser only, keeping our traversal and binary reading.** Caps the deletion at
  ~420 lines and leaves the two-stack duplication in place.
- **Collapsing `dataset.data` to `(x, y, z, frames)`** to preserve the existing
  downstream contract. Rejected: it keeps the frame-group reverse-engineering
  that has caused the multi-echo and DWI-multicycle problems, for a bisectability
  benefit the curated goldens already provide.
- **Vendoring `brukerapi`.** Zero dependency risk, but it means owning 6,000
  lines of someone else's reader — the exact opposite of the goal.

## Consequences

- **`get_value` raises where `.get` returned `None`.** There are 165 parameter
  accessor sites (44 `.get()`, 50 `[]`, 71 `lib.utils.get_value`). Our `.get(key)`
  returned `None` for a missing key; `brukerapi`'s `get_value(key)` raises
  `KeyError`. Because missing keys are *ParaVision-version dependent*, an
  unguarded site fails as "works on PV6, crashes on PV5.1". The upstream
  `get_value(key, default=None)` addition exists specifically to make this safe.
- **`--ignore-slope` and `--ignore-offset` stop being independent.** `brukerapi`
  exposes a single `scale` boolean, so offset cannot be applied without slope
  through `dataset.data`. Accepted.
- **Archive support regressed on the migration branch** until the upstream PR
  shipped. Resolved: isi-nmr/brukerapi-python#151 (path protocol,
  `get_value(key, default)`) and #152 (empty parameter value) are merged and
  released in 0.4.1, so `uv sync` resolves from PyPI and the branch is whole.
- `Dataset.ra` (random access) degrades to a full read for archive-backed
  datasets — `np.memmap` cannot address a compressed member.
- The `ctypes.cast(id(pvobj), py_object)` object resurrection in
  `api/data/scan.py` disappears with the rewrite, along with the use-after-free it
  caused (see the anchoring comment in `app/tonifti/scan.py`).
- `08_orientation_test.py` tests rotation math in isolation and cannot catch an
  axis-order regression. The goldens are the only guard; treat them as such.

## What implementation determined

Seven things the plan could not settle in advance.

- **`api/helper/slicepack.py` survives, reduced.** It was listed with the binary
  assembly, but what it computes — the number of slice packages, each pack's
  slice count and its slice distance — is geometry, and feeds the affine and the
  per-package image split. What it lost is its dependence on the frame-group
  parser: the Frame Groups now come from `dataset.dim_type` via
  `helper.frame_groups`. `api/helper/frame_group.py`, `api/helper/fid.py`,
  `api/helper/dataarray.py`'s parsing and `api/analyzer/dataarray.py` are gone.

- **One accessor, not 165 bare reads.** `lib.utils.get_value(parameters, key,
  default)` resolves the JCAMP-DX representation `brukerapi` deliberately leaves
  intact: it unwraps `<...>` string literals, re-types a numeric literal, treats
  an empty literal as absence, and returns a struct array as a list of rows even
  when it has one row. Without it a struct read flattens (`(a, b)` → `[a, b]`
  instead of `[[a, b]]`) and every string arrives quoted. It is the one seam
  where our representation meets the dependency's.

- **Disk slice order is deliberately un-applied.** `brukerapi` flips the slice
  axis for `VisuCoreDiskSliceOrder=disk_reverse_slice_order` so index 0 is the
  first `VisuCorePosition`; brkraw-legacy keeps the on-disk order and nudges the
  affine origin instead (`AffineAnalyzer._correct_origin`). Taking both would
  correct twice, so `BaseMethods._restore_disk_slice_order` undoes the flip and
  the affine is unchanged. Which convention is right is a geometry question —
  out of scope here, worth its own ticket. 49 of 2937 reconstructions in
  `resources/` are affected.

- **Four upstream defects fell out of the migration**, all fixed in `brukerapi`
  rather than worked around — the standing pattern this ADR sets, exercised four
  times in two days (isi-nmr/brukerapi-python#151, #152, #153 and #154, all
  merged and released in 0.4.1):

  - archive support needed `..`-relative traversal, because `zipfile.Path` joins
    textually and never collapses `..` (#151, with `get_value(key, default)`);
  - a parameter written with no value at all (`##$ACQ_operator= `) raised
    `IndexError` (#152);
  - `RECO_transposition` was applied on read though the reconstruction had
    already applied it (#153, see `EXPERIMENT_PLAN.md`);
  - which left `data.shape` disagreeing with `shape_final`, silently (#154).

  The upstream `get_value(key, default)` is *not* what our accessor calls —
  struct arrays need the `Parameter` object, so the default lands one level down
  — but it stays: it is what makes a bare `brukerapi` read safe for anyone else.

- **Opening the archive is the caller's job, by design.** `zipfile.Path` is
  constructed in `api/data/study.py` (`_archive_root`, ~10 lines) and handed
  over; that is what "callers pass a zipfile path object" means. Zero lines of
  archive *handling* is what moved upstream. `_require_archive_support` turns an
  older, path-only `brukerapi` into a message naming the version to install,
  rather than a `TypeError` about `os.PathLike` that reads like corrupt data.

- **`info`'s matrix size is the assembled shape now.** It used to print the
  collapsed matrix the deleted `_get_matrix_size` computed — non-slice frame
  groups multiplied into one trailing count, and the slice axis in a different
  position from the data (`256 x 256 x 9 x 8` where the array is
  `256 x 256 x 8 x 9`). It prints what `get_dataobj` returns: one axis per Frame
  Group, slice at k. Reproducing the old line would mean reintroducing exactly
  the reverse-engineering this change removes.

- **Three date parameters changed shape**, recorded in
  `tests/15_parameter_test.py::ACCEPTED_CHANGES`. The old parser split every
  value on `,`, chopping `2020-06-12T09:46:25,256+0200` into two strings.
  `SUBJECT_date`, `VisuAcqDate` and `VisuCreationDate` are now one string each,
  and `get_scan_time` parses them with an anchored match rather than a
  substitution over the whole value.

Verification ran at three widths. The curated set — 159 images across PV5.1,
PV6.0.1 (including a reverse-slice-order study), PV7.0.0, PV360, a `.zip` and a
`.PvDatasets` — is bit-identical: affine, data hash, shape, word type and header
field for field. The full local corpus, 1,570 reconstructions under
`resources/testdata`, was swept the same way. Committed as a regression test is
the subset reachable from the public fixtures (`tests/goldens/images.json`, 122
images over the four ParaVision generations, plus an archive built from one of
them at test time), because a golden is only useful where the data can be
fetched.

## Do not re-litigate

Do not reintroduce a JCAMP-DX parser, a directory/archive walker, or a
byte→array assembler into this repository. If `brukerapi` cannot express
something we need, fix it upstream — that is the standing pattern, not the
exception. `api/pvobj/` and `lib/pvobj.py` were deleted deliberately.
