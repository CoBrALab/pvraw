# BIDS conformance plan

How pvraw gets from "zero validator errors" to "everything Bruker records,
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

Track 1 is complete. The full-corpus sweep (`tools/sweep_bids.py`) runs 97
units at **0 pipeline errors and 0 validator-flagged**. Roughly 375 of those remaining are fields
Bruker simply does not record, so they are not a backlog.

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
would reintroduce exactly what ADR 0002 removed. Filed upstream as
[isi-nmr/brukerapi-python#189](https://github.com/isi-nmr/brukerapi-python/issues/189),
asking for `configscan` to be loaded as an optional parameter file alongside `reco`
and `d3proc`. `GradientSetType` becomes mappable if that lands.

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

### PR5 · Modality-agnostic and tabular files — done

New `lib/tabular.py` builds the rows. It takes parameter objects rather than a
loader, so a row can be built and tested without a dataset on disk.

`participants.tsv` carries `participant_id`, `species`, `age`, `sex` and `weight`,
each described in `participants.json` — `weight` is not a BIDS-defined column, and
an undescribed non-standard column is a warning. `age` is **derived** from
`SUBJECT_dbirth` and the study date and the birth date is then discarded, since
BIDS has an age column and no birth-date column. `sex` reads all four version
spellings and treats `UNDEFINED`/`UNKNOWN` as absence. `weight` treats ParaVision's
`0.001` sentinel as absent. `strain` and `handedness` are omitted — no source.

`_scans.tsv` and `_sessions.tsv` carry `acq_time` from `VisuAcqDate`, the
acquisition *start*, which is what BIDS asks for — not `VisuCreationDate` (when the
reconstruction was written) and not `get_scan_time`'s `scan_time`, which adds the
duration and so is the end. The times are the scanner clock as recorded; the README
says to shift dates before sharing, because a converter cannot do that without
destroying timing the user may still need.

**`species` is written as `n/a` rather than omitted, which reverses what "no source"
would suggest.** BIDS reads an *absent* species column as `homo sapiens`, so
omitting it would make every animal dataset silently claim to be human — the same
failure as a bare `PhaseEncodingDirection`. No binomial name is derivable, so `n/a`
it is, plus a warning.

**The taxon comes from the subject frame, not the subject file.** ParaVision picks
its coordinate system per specimen (PV6.0.1 manual S1.3.6: Rodent for quadrupeds,
Primate for bipeds, Material for phantoms), so it is read per scan from
`VisuSubjectType` and resolved by `uses_quadruped_frame` — the same rule the affine
uses, not a second copy of it. That distinction is the whole point: PV5.1 cannot
express a subject type and writes `SUBJECT_type=Human` for **every** study
regardless of specimen, so the first version of this, which read the study
`subject` file, stayed silent on exactly the rodent data where the human default
does most harm. A quadruped answer is definite; a biped answer only narrows the
subject to a primate.

`generateModalityAgnosticFiles` no longer calls `sys.exit()` when
`participants.tsv` exists, so a subject can finally be added to a converted
dataset, and `.bidsignore` is no longer written — its only content was `etc/`, for
scans that are skipped and never emitted.

### PR6 · Routing — done

**A derived reconstruction turned out to be a stack, not an image**, which is what
made this more than moving files. An ISA fit writes five volumes and a DTI
reconstruction twenty-two, each index meaning something different:

```
[0] signal intensity              [3] std dev of T2 relaxation time
[1] std dev of signal intensity   [4] std dev of the fit
[2] T2 relaxation time            <- the only volume BIDS has a suffix for
```

Both identifiers are machine-readable and consistent on PV5.1 and PV6:
`VisuFGOrderDesc` names the model, `VisuFGElemComment` names every element. So new
`lib/derived.py` finds the map by **label** rather than position, and the converter
writes that one volume as raw `anat/..._T1map|T2map.nii.gz`.

**The units were the catch.** BIDS states T1map/T2map are "In seconds (s)" and
ParaVision fits in milliseconds, so writing the element as it stands is off by 1000.
The maps come out at 6.6002 s and 1.3295 s instead of 6600.19 and 1329.49.

The label check runs *before* the MSME branch, because an ISA T2 map is usually
fitted from an MSME scan — matching on the acquisition method would relabel the map
as `MESE`, the exact confusion this ends.

Everything else derived, and everything unclassifiable, is now **kept** rather than
dropped — 33 scans on the PV6 study. A ParaVision-computed stack with no single
suffix goes to `derivatives/pvraw/` with its own `dataset_description.json`
(`DatasetType: derivative`); a scan we could not classify goes to `sourcedata/`,
since it is not derived at all, only uninterpreted. Both directories are
validator-ignored by definition, so 33 recovered scans cost no errors and no
warnings.

### PR7 · `IntendedFor` and `B0FieldIdentifier` — done

`save_json` had accepted an `intended_for` argument all along and nothing ever
passed one, so every fieldmap came out unlinked and unusable without hand-editing.

Both mechanisms are written. `B0FieldIdentifier`/`B0FieldSource` pair by name and
survive a rename; `IntendedFor` is the path list most tools still read.

The rule — correctable images acquired **after** this fieldmap, up to the next one —
earns its complexity on the data we already have: on the PV6 study three dwi runs
precede the fieldmap by about an hour and one follows it, so "every dwi in the
session" would attach a fieldmap to scans acquired before it was measured.
Anatomical scans are never claimed; they are not EPI readouts.

Neither field has a Bruker source — nothing records what a fieldmap was measured
for — so the datasheet gets a `b0group` column, and rows sharing a label pair
regardless of acquisition order.

It runs **after** conversion, because `run-` indices are only resolved while
converting and `IntendedFor` must name what was actually written. PR5's `_scans.tsv`
rows already carry filename and `acq_time`, which is exactly the input.

### PR8 · ASL / `perf` — done

FAIR and CASL scans now convert to `perf/asl` with an `aslcontext.tsv`.

**Nothing about the frame-group layout is assumed.** Across the corpus the same
information appears as `(MOVIE, IRMODE)`, `(IRMODE, MOVIE)` — reversed by
`PVM_FairMode INTERLEAVED2` — `(SLICE, IRMODE, CYCLE)` and, for CASL,
`(SLICE, MOVIE, CYCLE)`. New `lib/asl.py` finds the labelling axis by **name**,
never by matching element counts: PV7 scan 16 has slice=2 *and* irmode=2, so
guessing between them would silently invert the perfusion signal.

Element labels are matched by prefix because there are three spellings — and the
third was not in any earlier survey of this data:

```
PV5.1        'Selective Inversion Mode' / 'Non-selective Inversion Mode'
PV6, PV7     'Selective Inversion'      / 'Non-selective Inversion'
PV7 (some)   'S TI: 1000.0 ms'          / 'NS TI: 1000.0 ms'
```

`S` prefixes both short spellings, so non-selective must be tested first or every
label reads as a control. An unrecognised label raises rather than falling back to
axis order.

Verified against all 8 ASL scans across three ParaVision versions: derived row
count equals written volume count in every one.

The schema encodes `aslcontext.tsv` as an *association*, not a required file, and
every ASL check is guarded on its presence — so a missing one **silently disables
all eleven ASL error checks**. That is why partial ASL support would not have been
a smaller deliverable, only an unmeasurable one.

Six required fields cannot be expressed as per-parameter mappings, so they are
computed in one place. Several are constants because ParaVision has no such
module: no FAIR or CASL method in any version present has background suppression,
a Q2TIPS/QUIPSS bolus cut-off or a flow crusher. `BolusCutOffFlag: false` is also
what keeps `BolusCutOffDelayTime`/`Technique` from being required.
`TotalAcquiredPairs` is `min(label, control)` because CASL in `Dynamic` mode sets
the two counts independently. **No pCASL method exists in any ParaVision version
present**, so `PCASLType` is permanently unmappable rather than merely unmapped.

Two bugs found by validating rather than by reading:

- `a or b` **raises** on an array, and `VisuAcqRepetitionTime` is one on a
  variable-TR scan. That aborted all four ASL conversions *after* the image was
  written, leaving an orphan NIfTI and duplicate `_scans.tsv` rows.
- PV5.1 exposed a PR6 bug: scan 31 is `FG_ISA × FG_ECHO`, five maps over five
  echoes, and the multi-echo branch split it into `echo-N_T1map` — but BIDS has no
  `echo` entity for a parametric map. A fit repeated along another axis has no
  single map to extract, so the whole stack goes to `derivatives/`. PR6 had been
  validated on PV6 only.

## What the full-corpus sweep caught, and why it should run first

`tools/sweep_bids.py` converts and validates **every** study in the corpus. Run
after PR8, it flagged 11 of 97 units with `SIDECAR_WITHOUT_DATAFILE` — a
regression introduced back in PR5, which moved `participants.tsv` to be written
only when there are rows but left `participants.json` written unconditionally. In
a study where every scan is unclassifiable there are no rows, so the sidecar
described a table that was never created.

Every PR in this stack was validated against one to three hand-picked studies, all
of which convert something. The class of study where the answer is "nothing
converts" was never exercised. All 11 units were already in the corpus — the gap
was in what got run, not in the data available.

**The sweep belongs before each PR, not after the last one.** After the fix: 97
units, 0 pipeline errors, 0 validator-flagged.

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

Completion bar: every parameter `pvraw` reads, every parameter that appears
in real ParaVision files, **and** chapter-complete against the manuals' own Data
Formats chapters.

The document stays a generic specification of the format. Datasets that are publicly
reachable **may** be cited — cite the public URL, so a reader can follow it. Local-only
data under `resources/` is used to verify facts, never cited.

First known gap: the entire `PVM_Enc*` family (`PVM_EncSteps1`, `EncValues1`,
`EncOrder1`, `EncStart1`, `EncCentralStep1`) is undocumented, although every method
file writes it and it is the only record of k-space traversal order.

## Verification

- `tools/sweep_bids.py` for validator error counts, **before** each PR as well as
  after. Hand-picked studies all convert something; only the sweep exercises the
  study where nothing does, which is where this stack's one regression hid.
- `tools/sweep_nifti.py --compare` for anything that could move geometry.
- The offline value test keeps the fast suite honest between `data` runs.

## What deliberately stays a warning

Verified to have no Bruker source: `NonlinearGradientCorrection`,
`InstitutionAddress`, `InstitutionalDepartmentName`,
`AnatomicalLandmarkCoordinates`, `B0FieldIdentifier`/`B0FieldSource`, `species`,
`strain`, `handedness`, `events.tsv`, and `Authors`/`License` in
`dataset_description.json`.

Plus `PhaseEncodingDirection`, until Track 2 resolves it.
