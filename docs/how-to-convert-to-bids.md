# How to convert Bruker studies to BIDS

Directions for the tasks that come up when converting real data. It assumes you know
what BIDS is and what you want your dataset to look like. If you have never run a
conversion, start with [Tutorial: your first conversion](tutorial-first-conversion.md).

Conversion is two commands with your judgement in between:

```bash
uv run pvraw bids_helper <parent_dir> bids_map -j    # 1. propose a datasheet
#                                                              2. edit bids_map.csv
uv run pvraw bids_convert <parent_dir> bids_map.csv -j bids_map.json -o <output>
```

`<parent_dir>` holds one or more study directories or `.zip`/`.PvDatasets` archives.
`bids_helper` guesses; the datasheet is where you correct it. Everything below is about
that middle step.

## Decide what each scan becomes

Open `bids_map.csv`. One row per reconstruction. Only these columns change the output:

| Column | Effect |
|---|---|
| `SubjID`, `SessID` | the `sub-` and `ses-` labels |
| `DataType` | the BIDS datatype directory: `anat`, `func`, `dwi`, `fmap`, `perf`, or `etc` |
| `modality` | the BIDS suffix: `T2w`, `bold`, `dwi`, `fieldmap`, `asl`, … |
| `task`, `acq`, `ce`, `rec`, `dir` | the matching BIDS entities |
| `run` | the run index; leave blank to have them numbered for you |
| `b0group` | which fieldmap covers which scans (see below) |
| `Start`, `End` | crop volumes off a series |

The datasheet also carries `inv`, `flip`, `mt` and `part` columns. **They are not
currently read** — filling them changes nothing. Use `acq` if you need to distinguish
such scans by name.

A row with `DataType` set to `etc`, or with `modality` blank, does not enter the
validated tree. Its data is still converted — see *Find the scans that did not become
BIDS* below.

## Deal with scans marked `etc`

`bids_helper` marks a scan `etc` when it will not guess. The warnings it prints say
which case applies:

- **The method is not recognised.** Set `DataType` and `modality` yourself.
- **A single-volume EPI.** It is not a BOLD time series. Make it `anat`, or give it a
  `DataType`/`modality` that describes what it is.
- **A derived reconstruction with no single BIDS suffix** — a DTI tensor stack, for
  instance. Leave it. It goes to `derivatives/`.

If you set `DataType` and `modality` to something invalid for BIDS, the conversion
stops with the list of valid suffixes for that datatype rather than writing it.

## Name an fMRI task

`func` needs a `task` entity and a matching `TaskName` in the sidecar. `bids_helper`
prefills `task` from the Bruker protocol name, which is rarely what you want:

```csv
DataType,task,modality
func,revNoTrigAdjPEOffEPI,bold      →      func,rest,bold
```

Edit the `task` column; `TaskName` follows it automatically. Use only letters and
digits — the converter rejects anything else with the offending cell reference.

If the task is not resting state, the validator will warn that `events.tsv` is missing.
That file describes your stimulus timing, which the scanner does not record. Write it
yourself, or accept the warning.

## Separate repeats into runs

Leave `run` blank and rows that would otherwise collide are numbered in datasheet
order — `run-01`, `run-02`, and so on.

Set `run` explicitly when the order matters, for instance when a mid-session scan
failed and you want the numbering to reflect the intended sequence. Every row sharing a
filename and modality must then have a distinct `run`, or the conversion stops and
names the conflicting scan.

## Link a fieldmap to the images it corrects

By default each fieldmap claims the correctable images acquired **after** it, up to the
next fieldmap. That matches how sessions are usually run, and it is written into both
`IntendedFor` and `B0FieldIdentifier`.

When it does not match — a fieldmap acquired at the end of the session for scans that
came before it, or two interleaved series — set `b0group` to the same label on the
fieldmap and on every scan it covers:

```csv
ScanID,DataType,modality,b0group
5,dwi,dwi,pair1
9,fmap,fieldmap,pair1
```

Rows sharing a label are paired regardless of acquisition order. A single `b0group`
value switches that subject and session to explicit pairing, so label every fieldmap in
it, not just the awkward one — an unlabelled fieldmap in a session that uses labels
claims nothing.

Anatomical scans are never claimed by a fieldmap, whatever you label them.

## Crop volumes off a series

Set `Start` and `End` to the volume range you want kept. Both are indices into the
series:

```csv
ScanID,modality,Start,End
6,fieldmap,0,1
6,magnitude,1,2
```

This is how a two-echo field map is split into its `fieldmap` and `magnitude` parts —
`bids_helper` writes those two rows for you.

## Get subject details into `participants.tsv`

Sex, weight and date of birth come from the study's `subject` file. Age is derived from
the birth date and the study date; the birth date itself is never written.

Nothing needs setting for these. Two need your attention afterwards:

- **`species` is always `n/a`.** ParaVision records a body plan — `Biped`, `Quadruped`,
  `Phantom` — never a binomial name. Fill it in. BIDS reads an *absent* species column
  as `homo sapiens`, which is wrong for most preclinical data, so the converter warns
  when the subject was acquired in the rodent frame.
- **Blank sex or weight** means ParaVision recorded `UNKNOWN`, or its `0.001` unset
  sentinel. Fill them in from your records if you have them.

## Fix a wrongly recorded subject type or position

If the operator set the subject type or position wrongly at the scanner, the affine
will be wrong. Override at conversion time rather than editing files:

```bash
uv run pvraw bids_convert ... -t Quadruped -p Head_Prone
```

`-t` takes `Biped`, `Quadruped`, `Phantom`, `Other` or `OtherAnimal`. `-p` takes
`<BodyPart>_<Side>`, where body part is `Head`, `Foot` or `Tail` and side is `Supine`,
`Prone`, `Left` or `Right`.

## Add a subject to a dataset you already converted

Point `bids_convert` at the same `--output` directory with a datasheet covering the new
studies. `dataset_description.json`, `README` and `CHANGES` are left as they are, and
`participants.tsv` gains the new rows while keeping the ones already there. Converting a
subject a second time updates its row rather than adding a duplicate.

## Check the result

```bash
uv run bids-validator-deno <output> --schema v1.11.1
```

Use the same schema version the converter wrote into `dataset_description.json`, so the
dataset is checked against what it claims to be.

Expect **zero errors**. Warnings are expected and mostly not actionable: they are BIDS
asking for fields Bruker does not record — `InstitutionAddress`, `ReceiveCoilName`,
`NonlinearGradientCorrection` and similar. Two are worth acting on:

- **`NO_AUTHORS` / `TOO_FEW_AUTHORS`** — add `Authors` to `dataset_description.json`.
- **`EVENTS_TSV_MISSING`** — supply `events.tsv` for a task-based scan, or rename the
  task to `rest` if that is what it was.

## Find the scans that did not become BIDS

Nothing is dropped. Anything outside the validated tree is in one of two places:

- `sourcedata/` — scans that could not be classified.
- `derivatives/pvraw/` — ParaVision-computed stacks with no single BIDS suffix,
  such as DTI tensor reconstructions.

Both are named `sub-<id>[_ses-<id>]_scan-<n>_reco-<n>.nii.gz`, so a file traces back to
the scan it came from. Neither directory is validated, which is why keeping them costs
no errors.

To pull one of these into the dataset proper, set its `DataType` and `modality` in the
datasheet and convert again.

## Convert without BIDS

If you want NIfTI files and no BIDS structure:

```bash
uv run pvraw tonii <study>                    # one study
uv run pvraw tonii_all <parent_dir> -o <out>  # every study beneath a directory
```

`tonii_all` writes a plain `sub-<id>/ses-<id>/<datatype>/` tree with no sidecars,
datasheet or modality-agnostic files. Without `-o` it writes to `Data` in the current
directory.

Both commands skip localizer/tripilot scans. Pass `--no-ignore-localizer` when you want
those too — every on/off option has a `--no-` form.

## Related

- [Tutorial: your first conversion](tutorial-first-conversion.md) — a first conversion
  on a public sample study, end to end
- [`README.md`](../README.md) — commands, options and the Python API
- [ADR 0001](adr/0001-single-affine-implementation.md) — how orientation is derived
- [ADR 0002](adr/0002-delegate-bruker-reading-to-brukerapi.md) — why file reading is
  delegated to `brukerapi`
