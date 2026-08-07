# BIDS conformance plan

How BrkRaw-legacy gets from "zero validator errors" to "everything Bruker records,
said in BIDS". Written 2026-08-07.

## The constraint

Extract the maximum information the Bruker raw data holds and present it in BIDS
form — JSON sidecars and the BIDS tabular/modality-agnostic files.

**Zero validator errors is a hard limit, not a target.** Warnings are acceptable
only where no Bruker source exists. Where a value is real but cannot be expressed
as valid BIDS, it is written under a deliberate non-schema key rather than dropped
or written invalid.

Two facts shape everything below:

- The validator maps missing OPTIONAL fields to `ignore`. It emits **no issue at
  all** for them. So "maximum extraction" cannot be measured from validator output;
  it needs a systematic walk of the schema's own field list.
- `bidsschematools` parses selector expressions but ships **no evaluator**. Only the
  Deno validator has one. So the schema is used here for *values* (each
  `objects.metadata` entry is valid JSON Schema) and the Deno validator remains the
  authority on *which* fields apply.

Three tracks. Track 1 is a PR stack in dependency order; Tracks 2 and 3 run beside
it and block nothing.

## Track 1 — the PR stack

PR1–PR4 are done. On the PV6 lego phantom the validator reports **0 errors**
throughout, with warnings 499 → 429.

### PR1 · Schema pin and version unification — done

`BIDSVersion` comes from `schema.bids_version` instead of a literal. Dependency
floor raised to `bidsschematools>=1.2`. `_supporting_bids_ver` derived, not
hardcoded. `tests/06_bids_test.py` asserts against the schema rather than
`'1.10.0'`. CI pins the validator to the concrete latest **release** tag, never
`latest` — `latest` tracks the spec's master branch and can turn CI red overnight.

First, because everything downstream asserts against the version.

### PR2 · The value checker — done

Shipped in `lib/bids.py` and called by `save_json`, so it also catches bad values on
users' own data, which is where the last several of these bugs lived. Each emitted
value is validated against `objects.metadata[<field>]` as JSON Schema, with
`objects.formats` patterns registered as format checkers. `jsonschema` becomes a
declared runtime dependency.

On failure: warn, omit the BIDS key, and write the raw value under a `<key>Raw`
non-schema key. Writing a value already proven invalid would produce
`JSON_SCHEMA_VALIDATION_ERROR` (`"level": "error"`), which the hard limit forbids;
silently dropping it would lose information the whole converter exists to preserve.

Offline, so it runs in `pytest -m "not data"`.

**This check is deliberately stricter than the reference validator, and that is not
redundant.** The validator only value-checks a field named by a rule group whose
selectors pass. `RepetitionTime` is named in just two groups —
`func.MRIFuncRepetitionTime` and `mrs.MRSRepetitionTime` — so on an `anat` file it
is never type-checked at all. Two PV6 and five PV5.1 sidecars were shipping
`"RepetitionTime": [0.5, 1.18, 5.0]` from variable-TR RAREVTR scans, an array where
BIDS wants one number, with the validator reporting zero errors. Checking every
emitted value, rather than only the ones a rule happens to name, is what finds these.

*Correction to an earlier draft of this plan:* the guard test — a schema field
neither mapped nor explicitly marked unmappable fails the build — was listed here.
It belongs to PR3, because the table it enforces is not populated until then.

### PR3 · `reference.py` becomes the complete verdict table — done

Delete the dead `COMMON_METADATA_FIELD` (no Python file reads it). Every schema
field gets an entry: mapped, or `None` with the reason it cannot be. `CoilConfigName`
marked as a deliberate non-schema key.

Three claims in the file are wrong and get corrected:

| Field | Comment claims | Reality |
|---|---|---|
| `CoilCombinationMethod` | no source | `RecoCombineMode` — `SumOfSquares`/`ShuffleImages`/`AddImages` |
| `GradientSetType` | "no Bruker parameter encodes a gradient set type" | `CONFIG_SCAN_gradient_system` |
| `MultibandAccelerationFactor` | "no parameter on PV5/6/7" | true for PV5.1/PV6, **false for PV7/PV360** (`PVM_MbEncAccelFactor`) |

`reco` is added as a fourth parameter source, which unlocks `CoilCombinationMethod`.
`CONFIG_SCAN_gradient_system` lives in `configscan`, which `brukerapi` does not load,
so `GradientSetType` stays unmapped with a corrected comment — reading that file here
would reintroduce exactly what ADR 0002 removed. **Still open:** an upstream
`brukerapi` issue asking it to expose `configscan` has not been filed yet.

`RepetitionTime` needs the guard `InversionTime` already has: variable-TR sequences
(RAREVTR) return an array, and `{'TR': 'VisuAcqRepetitionTime', 'Equation': 'TR/1000'}`
passes it straight through. Found by PR2's checker, which demotes it safely in the
meantime.

Two mappings fail silently on PV5.1 and are fixed: `AcquisitionDuration` reads
`PVM_ScanTime`, which does not exist there (`VisuAcqScanTime` does, and is identical
where both exist); `NumberOfVolumesDiscardedByScanner` reads `PVM_DummyScans`, also
absent on PV5.1 (`NDummyScans` there) and counting **TR periods, not volumes**, so it
gets gated to EPI.

No deprecated field is emitted. `AcquisitionDuration` is deprecated for `func` and
merely optional elsewhere, so it is dropped for func and kept for anat/dwi.

`PhaseEncodingDirection` is omitted; `PhaseEncodingAxis` is emitted instead — see
Track 2 for why.

### PR4 · Gap fields — done

18 fields mapped, leaving **8** in the gap list. The verdict table now stands at
53 mapped, 3 computed at write time, 8 known-but-unmapped, 32 with no Bruker
source, 2 deliberate non-BIDS keys.

Mapped: `MTState`, `SpoilingState`, `SpoilingType`, `SpoilingRFPhaseIncrement`,
`SpoilingGradientDuration`, `SpoilingGradientMoment`, `RepetitionTimeExcitation`,
`RepetitionTimePreparation`, `ParallelReductionFactorOutOfPlane`,
`ParallelAcquisitionTechnique`, `MultibandAccelerationFactor`, `WaterSuppression`,
`WaterSuppressionTechnique`, `B0ShimmingTechnique`, `DelayTime`,
`DelayAfterTrigger`, and `EchoTime1`/`EchoTime2` (in `FIELDMAP_META_REF`, since on
a multi-echo anat the first two echoes of a train are not a phase-difference map).

**Checking each mapping against real values, rather than against the parameter's
name, caught three wrong claims**: `PVM_MagTransPulse1` is a struct *row*, not a
flat array; `PVM_WsOnOff` and `PVM_WsMode` disagree in real data (`On/NO_SUPPRESSION`
14×, `Off/VAPOR` 2×) so neither alone answers "was water suppressed"; and
`PVM_EncPpi` has 2 elements in 2D, 3 in 3D, so an unguarded `[2]` raises on every
2D scan.

**Equations can now read strings.** `meta_check_express` replaced every string
input with `None` before `eval`, which made every Bruker enum unusable — and had
been silently dropping `DeviceSerialNumber` (`str(SN)` over a string parameter)
from every sidecar. 52 → 1 missing after the fix.

**Which spoiler BIDS means, settled from the pulse programs.** The end-of-TR lobe
is `ReadSpoiler` for the FLASH family (`g6`, played after the ADC) and
`RepetitionSpoiler` for the RARE family (`d9 grad_ramp{g1,0,g1} ;TR spoiler`).
`SliceSpoiler` fires *before* excitation and is not it. The derived moment is
verified against Bruker's own `spoil` field — the intended dephasing in cycles per
pixel, which the derivation does not use — and `γ · moment · voxel_size`
reproduces it exactly across nine methods and two ParaVision versions.

The 8 that remain are not oversights. Each is unverifiable here, with the entry
saying what would settle it: the five MT pulse fields (`PVM_MagTransOnOff` is
`Off` in all 1642 corpus files, so they describe a module that never played),
`ScanOptions` (ParaVision leaves that DICOM tag empty, so the codes would be ours
to invent), `B1ShimmingTechnique` (`AutoAdj` is coil scaling), and
`ContrastBolusIngredient` (PV360-only, absent from the corpus).

Traps carried into the mappings: in 3D, `PVM_SliceThick` is the whole slab, not the
voxel; `PVM_SpatResol` is already anti-alias corrected, so deriving from
`PVM_EncMatrix` is wrong; `PackDel`'s floor of 0.001 ms means "no delay";
`PVM_TriggerDelay` must be gated on `PVM_TriggerModule`; no Bruker pulse shape maps
to the BIDS `FERMI`, `GAUSSHANN`, `SINCHANN` or `SINCGAUSS` values.

**Warnings do not only fall.** Emitting a field can activate a conditional rule:
`rules.sidecars.mri.SpoilingGradient` selects on `SpoilingType` being `GRADIENT`
or `COMBINED` and then recommends the moment and duration. Errors stay 0, which is
the limit; the warning count is a weaker signal than it looks.

### PR5 · Modality-agnostic and tabular files

`participants.tsv` gains `sex` and `weight` (kg, 1:1 — but `0.001` is ParaVision's
unset sentinel) and a **derived** `age`; the birth date itself is never written,
since BIDS has no column for it. Version fallbacks are needed because PV360 renames
half the subject class. `species`, `strain` and `handedness` are omitted — no source
exists, and `SUBJECT_type` is body plan, not taxonomy (and its enum identity changed
between PV5.1 and PV6, so a numeric read mis-decodes).

`_scans.tsv` and `_sessions.tsv` with the **true** `acq_time`. Shifting dates before
sharing is the user's job, and the generated README says so — a converter that
silently destroys timing is worse than an honest one.

`generateModalityAgnosticFiles` stops calling `sys.exit()` when `participants.tsv`
already exists, which currently makes it impossible to add a subject to an existing
tree. The dead `etc/` line in `.bidsignore` goes.

### PR6 · Routing

Bruker ISA relaxation maps go to **raw** `anat/` under their qMRI suffix — `T1map`,
`T2map`, `R1map`, `R2map`, `T2starmap`, `MTRmap`, `S0map`, `M0map`, `PDmap` and
`MWFmap` are all valid raw anat suffixes, so no derivatives tree is needed for them.
DTI tensor images have no raw suffix and go to `derivatives/brkraw-legacy/` with its
own `dataset_description.json`. Unclassifiable scans go to `sourcedata/`. Both are
validator-ignored by definition, so the data is preserved without costing an error.

### PR7 · `IntendedFor` and `B0FieldIdentifier`

Rule: same-session EPI-family images acquired after this fieldmap and before the
next. Assigning every func/dwi in the session is wrong whenever a session has two
fieldmaps, which is the normal case.

Both mechanisms are emitted. `B0FieldIdentifier`/`B0FieldSource` pair by name and
survive renaming; `IntendedFor` is still what most tools read. Neither has a Bruker
source — they are synthesised organisational labels, i.e. inference about intent,
not extracted information. A datasheet column overrides them.

### PR8 · ASL / `perf`

Largest, therefore last.

`perf` added to `DATATYPES`; `default_suffix` gains a `perf` branch. The
force-to-`etc` branch is replaced, keyed off `##$Method` only and ordered ahead of
the `epi`→`func` match (`FAIR_EPI` and `CASL_EPI` both contain "epi").

`aslcontext.tsv` is built from `VisuFGOrderDesc` + `VisuFGElemComment`, flattened in
Fortran order with `FG_SLICE` excluded. It **fails loudly** if the element comments
are not the known values, and never falls back to axis order — `PVM_FairMode`
`INTERLEAVED2` reverses the frame-group order, and the single-inversion modes
produce no `FG_IRMODE` axis at all.

The schema encodes `aslcontext.tsv` as an *association*, not a required file, and
every ASL check is guarded on its presence. A missing one therefore **silently
disables all eleven ASL error checks** rather than erroring — which is why partial
ASL support is not a smaller deliverable, it is an unmeasurable one.

Six required fields cannot be written in `reference.py`'s mini-language, because they
need the method name, the frame-group layout and the written volume count, none of
which `meta_check_express` can see: `ArterialSpinLabelingType`,
`BackgroundSuppression`, `M0Type`, `TotalAcquiredPairs`, and the per-volume
`PostLabelingDelay` / `RepetitionTimePreparation`. They are computed in
`save_json`/`build_bids_json`, as `SliceTiming` and `RepetitionTime` already are, and
`reference.py` carries an entry for each pointing at where.

Values with no Bruker source anywhere: `M0Type` is `"Absent"`;
`BackgroundSuppression`, `BolusCutOffFlag` and `VascularCrushing` are constant
`false`, since no such module exists in any ParaVision version present.
`TotalAcquiredPairs` is `min(label, control)` — in CASL `Dynamic` mode label and
control counts are set independently, so one warning there is unavoidable.

`ArterialSpinLabelingType` is `PASL` (FAIR) or `CASL`. **No pCASL method exists in
any ParaVision version present**, so `PCASLType` and every `BolusCutOff*` field is
permanently unmappable, not merely unmapped.

Multi-echo ASL needs one shared `aslcontext.tsv` — the suffix takes no `echo`
entity, but `build_bids_json` appends `_echo-N_` unconditionally today.

`test_asl_scans_not_auto_classified` is rewritten; it currently asserts the opposite.

## Track 2 — the phase-encode sign (research, non-blocking)

BIDS has **no unsigned value** for `PhaseEncodingDirection`: "the polarity is assumed
to go from zero index to maximum index unless `-` is present". So emitting a bare
`j`, as the code does today, is an affirmative claim of positive polarity — not the
abstention the comment in `reference.py` describes.

The sign is the product of three terms:

| Term | Meaning | Status |
|---|---|---|
| T1 | which voxel axis is PE | **derivable** — `VisuAcqGradEncoding`, declared in the image frame, so `RECO_transposition` is already handled |
| T2 | sign of dk/dt in the echo train | **derivable** — `PVM_EncSteps1`, verified in 1483 corpus scans |
| T3 | sorted k-row → image index, after ParaVision's own sort and FFT | **written nowhere** |

T3 is one unknown sign per ParaVision generation. Because 167/167 EPI scans in the
corpus ascend, T2 is constant, so today's bare `j` is *always right or always wrong*
per generation with nothing to say which.

The corpus contains no reversed-PE pair (0/1483 descending `PVM_EncSteps1`,
`ReversePE=NoRevPhase` 15/15). But it contains **191 exact-geometry EPI/undistorted
pairs**, so T3 can be measured from the direction in which the EPI distorts relative
to a matched RARE. The best candidate is a 2% agar phantom with high-susceptibility
surface material (PV6.0.1, EPI scan 11 vs RARE scan 6).

**Bar for "verified": two or more independent agreeing pairs per generation.** One
measurement is a single sample of a quantity we have no other handle on, and a
phantom near-symmetric along the PE axis gives an ambiguous reading.

A signed `PhaseEncodingDirection` is emitted only for a generation and method where
that passed. Everywhere else, `PhaseEncodingAxis` alone. `EXPERIMENT_PLAN.md` gains
the phase-encode item. If this does not resolve, the deliverable is the written-down
experiment, and it holds nothing else up.

For the record: no Bruker converter emits a signed PE direction. BrkRaw 0.5+ emits
none; `bruker2nifti`, `Bru2Nii`, `dicomifier` and `pvconv` emit no sidecar at all;
dcm2niix has no Bruker path and, where it cannot determine polarity, emits the same
non-standard `PhaseEncodingAxis` key. Upstream BrkRaw#91 — "not sure how to determine
the sign" — has been open since 2022.

## Track 3 — FILE_FORMAT.md

Completion bar: every parameter `brkraw_legacy` reads, every parameter that appears
in real ParaVision files, **and** chapter-complete against the manuals' own Data
Formats chapters.

The document stays a generic specification of the format. Datasets that are publicly
reachable **may** be cited — cite the public URL, so a reader can follow it. Local-only
data under `resources/` is used to verify facts, never cited.

First known gap: the entire `PVM_Enc*` family (`PVM_EncSteps1`, `EncValues1`,
`EncOrder1`, `EncStart1`, `EncCentralStep1`) is undocumented, although every method
file writes it and it is the only record of k-space traversal order.

## Verification

- `tools/sweep_bids.py` for validator error counts, before and after each PR.
- `tools/sweep_nifti.py --compare` for anything that could move geometry.
- The offline value test keeps the fast suite honest between `data` runs.

## What deliberately stays a warning

Verified to have no Bruker source: `NonlinearGradientCorrection`,
`InstitutionAddress`, `InstitutionalDepartmentName`,
`AnatomicalLandmarkCoordinates`, `B0FieldIdentifier`/`B0FieldSource`, `species`,
`strain`, `handedness`, `events.tsv`, and `Authors`/`License` in
`dataset_description.json`.

Plus `PhaseEncodingDirection`, until Track 2 resolves it.
