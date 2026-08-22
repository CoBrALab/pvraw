# ADR 0001: One affine/orientation implementation (`AffineAnalyzer`)

- Status: Accepted; superseded in part by [ADR 0002](0002-delegate-bruker-reading-to-brukerapi.md)
  (see the amendment below)
- Date: 2026-07-21

> **Naming.** This ADR predates the rename of the project from `brkraw-legacy` to
> `pvraw` (1.0.0). It is left in its original words as a dated record; `brkraw`,
> `brkraw-legacy` and `brkraw_legacy` below all refer to what is now `pvraw`.

## Context

Two independent implementations computed the same NIfTI affine from the same
Bruker parameters:

- **Loader path** — `BrukerLoader._get_affine` → `_get_orient_info`
  (`lib/loader.py`) → `lib/orient.py` (`build_affine_from_orient_info`,
  `get_origin`, `reversed_pose_correction`, `calc_eulerangle`).
- **app.tonifti path** — `AffineAnalyzer` (`api/analyzer/affine.py`) →
  `Orientation` (`api/helper/orientation.py`).

Both consume the same ground-truth parameters (see `FILE_FORMAT.md`):
`VisuCoreOrientation` (patient→image, `i = M·p`, §7.2/§12), `VisuCorePosition`
(first-voxel-center in the DICOM patient frame, §7.2), `VisuCoreDiskSliceOrder`
(§7.3), `VisuCoreSlicePacksSlices` (per-package slice counts, §7.10), and
`VisuSubjectType`/`VisuSubjectPosition` (§7.5/§7.7). They reimplemented the same
spec twice — the slice-orientation map, the reverse-slice correction, the
Euler-angle origin selection, the pose rotation, and the quadruped-frame
rotation each existed in two copies.

Duplication cost real correctness. The copies drifted: `lib/orient.get_origin`
carried live bugs in untested branches (`.argmaxs()`, an inverted axial
`argmax`/`argmin`) that the `AffineAnalyzer` path had already fixed. A whole
regression test (`08_orientation_test.py`) existed only to pin the two paths
together, and six commits churned it keeping them in sync. Every orientation fix
had to land in both places or silently desync.

The `app.tonifti` path was already the canonical, spec-faithful one, and image
assembly (`get_niftiobj`) had already been routed through it.

## Decision

There is **one** affine/orientation implementation: `AffineAnalyzer` (with
`Orientation`), reached through the `app.tonifti` API.

- `BrukerLoader.get_affine`, `get_niftiobj`, and `get_sitkimg` delegate through
  a single `_scan_bridge` helper to a `ScanToNifti`, so the loader/CLI path, the
  BIDS conversion, and the `app.tonifti` API share one affine and one header.
- Subject-type/position overrides ride through as explicit
  `subj_type`/`subj_position` arguments; `None` lets the analyzer read them
  per-scan from `VisuSubjectType`/`VisuSubjectPosition` (never the study
  `subject` file — PV5 writes `SUBJECT_type=Human` unconditionally, §7.5).
- Standalone (individually-exported) scan directories route through the
  scan-level `ScanToNifti`, which constructs a `PvScan` directly from an
  `acqp`/`method`/`pdata` directory (§1.2).
- `lib/orient.py` and the loader's `_get_affine` / `_get_orient_info` /
  `_assemble_standalone` / `_set_nifti_header` are deleted.

The loader keeps the non-affine parameter helpers it still needs
(`_get_slice_info`, `_get_spatial_info`, `_get_matrix_size`).

## Consequences

- **Locality:** an orientation fix lands in exactly one module. The two-path
  pinning test and its maintenance churn are gone.
- **Behaviour change (intended):** any dataset outside the test fixtures whose
  loader-path affine differed from the analyzer path now gets the analyzer's
  (bug-fixed) affine. This was not pinned with golden values; it is the intended
  correctness improvement.
- Standalone conversion now shares the same header/scale handling as every other
  scan (the tonifti `Header`), rather than a bespoke `_set_nifti_header`.

## Amendment, 2026-07-26: `AffineAnalyzer` no longer computes an affine

[ADR 0002](0002-delegate-bruker-reading-to-brukerapi.md), as amended, moved the
geometry boundary: `brukerapi` derives the voxel-to-patient affine and
brkraw-legacy takes it. So the class this ADR named as *the* implementation is
now the place the subject correction is applied, not the place the affine is
derived — `AffineAnalyzer.__init__` reads `Dataset.affine_of_package(i)`, and
`_calculate_affine`, `_compose_affine`, `_correct_origin` and the
slice-orientation map are deleted with everything else this ADR was arbitrating
between.

**What still binds.** The rule that mattered in practice, and the only geometry
brkraw-legacy still owns:

> Subject-type/position ride through as explicit `subj_type`/`subj_position`
> arguments; `None` reads them per-scan from
> `VisuSubjectType`/`VisuSubjectPosition`, never from the study `subject` file
> (PV5 writes `SUBJECT_type=Human` unconditionally, §7.5).

`brukerapi` deliberately leaves the subject frame out of its affine —
re-applying `VisuSubjectPosition` inside it was one of the defects that made the
old upstream affine wrong — so this is a boundary, not an overlap.
`AffineAnalyzer._correct_orientation` is where it lives, and
`08_orientation_test.py::test_pv5_subject_type_not_taken_from_subject_file`
pins it.

Also still binding: one affine path, reached through `app.tonifti` via
`_scan_bridge`; no loader-side affine; `lib/orient.py` stays deleted.

**Stale specifics.** The Decision's third bullet describes constructing a
`PvScan` from an `acqp`/`method`/`pdata` directory — `PvScan` and all of
`api/pvobj/` are deleted by ADR 0002; standalone directories now open as a
`brukerapi` `Experiment` (`api/data/study.py::_open_container`). `get_sitkimg`
was removed with SimpleITK support before that. Of the parameter helpers the
Decision's last line reserves for the loader, only `_get_slice_info` survives;
`_get_spatial_info` and `_get_matrix_size` are gone, their callers reading
`brukerapi`'s derived properties or `lib/utils.get_value` instead.

## Amendment, 2026-08-21: what the subject-position rotation is

The amendment above said `brukerapi` "deliberately leaves the subject frame
out of its affine", and the code described its rotation as "image frame to
subject frame, keyed by `VisuSubjectPosition`". Both were wrong about the
model, though right about the result for the data that matters.

**What the files do.** ParaVision writes `VisuCoreOrientation`/`VisuCorePosition`
in the DICOM patient frame of the position it was *told* —
`VisuSubjectPosition` = `ACQ_patient_pos`. The PV5.1/PV6 manuals define the
position as the map between magnet and subject axes (`ACQ_patient_pos`:
`Head_Supine` negates Gx and Gz, `Head_Prone` Gy and Gz, …), and
`GTB_ObjPosMatrix(ppos, m, dicom)` in `PvGeoTools.h` "converts magnet
coordinate system into object coordinate system" keyed by that position. So
`brukerapi`'s affine is already anatomical — for the *declared* position, and
only if that declaration was true. Preclinical practice routinely leaves
ParaVision's default `Head_Supine` on a prone animal: 2,589 of 3,009 `visu_pars`
in `resources/testdata` declare `Head_Supine`.

**Decision.** pvraw does not trust the declaration. It assumes the animal lay
prone, head first (`ASSUMED_POSITION = 'Head_Prone'`), and rotates the
declared frame into the actual one:

```
correction = R(actual).T @ R(declared)      # then the quadruped convention
```

where `R(pose)` (`SUBJECT_POSE_ROTATION`) takes the frame ParaVision writes for
`pose` to the one it writes for `Head_Prone`, derived from the manual's table
as `R(pose) = M_Head_Prone @ M_pose.T` with `subject = M_pose @ magnet`. With no
override the correction is `R(declared)` — exactly what the code always did, so
default output does not move (`tools/sweep_nifti.py --compare` over the zenodo
corpus: 0 differing images).

**What changes.** `--position X` / `override_position(X)` now means *the animal
was actually in X*. Before, it replaced the declared value, so it meant "actual
position" only when the file declared `Head_Prone`; on a `Head_Supine` file,
`--position Head_Prone` ("my mice were prone") removed the correction and
flipped the output, and there was no way to say "trust the declaration" for a
genuinely supine subject. Now `--position <declared>` leaves `brukerapi`'s
affine alone, and `--position Head_Prone` is the default.

The four quarter-turn entries (`Head_Left`, `Head_Right`, `Foot_Left`,
`Foot_Right`, and their `Tail_*` aliases) change sign to match the manual;
their previous sign had no source. No acquisition in the corpus declares any of
them, so they rest on the manual alone (`08_orientation_test.py::MANUAL`).

**Evidence.** Two SAMRI mouse TurboRARE studies from one lab, both animals
prone, one declared `Head_Supine` (`20151208_182500_4007_1_4`, PV6.0) and one
`Head_Prone` (`20180730_053743_6587_1_1`, PV6.0): their `brukerapi` frames
differ by a half turn about F→H, and the corrected output was reviewed on
labelled renders and judged correctly oriented for both. Fitting the map from
`ACQ_grad_matrix` to `VisuCoreOrientation` over the corpus reproduces the
manual's table exactly (PV5.1/6/7 one fixed map for both positions; PV360 one
map per position) — FILE_FORMAT.md Section 12.

**What still binds.** One affine path; the declared type and position are read
per scan from `VisuSubjectType`/`VisuSubjectPosition`, never from the study
`subject` file; the quadruped convention is a fixed-frame rotation applied
after the pose rotation. `AffineAnalyzer._correct_orientation` is still the one
place.

## Do not re-litigate

Do not reintroduce a loader-side affine or a second orientation module. If a new
entry point needs an affine, feed a `ScanToNifti`/`AffineAnalyzer` — do not
recompute it from `visu_pars`, and (per ADR 0002, amended) do not recompute it
from `brukerapi`'s parameters either: take `affine_of_package`. The deletion of
`lib/orient.py` was deliberate.
