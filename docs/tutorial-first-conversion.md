# Tutorial: your first conversion

In this tutorial you will take a raw Bruker ParaVision study and turn it into a
validated [BIDS](https://bids.neuroimaging.io) dataset, using nothing but `pvraw`
and a text editor. Along the way you will inspect the study, convert it to plain
NIfTI, and see how the BIDS datasheet works.

You do not need your own scanner data. We use a small public sample study
(7 MB), and every step below works exactly as printed. Expect the whole thing to
take about fifteen minutes.

You need:

- [`uv`](https://docs.astral.sh/uv/) installed;
- an internet connection;
- a text editor (or a spreadsheet program) for one CSV file.

## 1. Install pvraw

Install the command-line tool onto your `PATH`, isolated from your other
environments:

```bash
uv tool install git+https://github.com/gdevenyi/pvraw.git
```

Check that it worked:

```bash
pvraw --version
```

This prints the installed version. If your shell cannot find `pvraw`, run
`uv tool update-shell`, then open a new terminal and try again.

## 2. Get a study to work on

Make a fresh directory and download the sample study — a ParaVision 6.0.1
acquisition containing a localizer, two anatomical scans, a field map and an
EPI:

```bash
mkdir pvraw-tutorial
cd pvraw-tutorial
curl -LO https://github.com/BrkRaw/brkraw-dataset/raw/main/PV6.0.1/UNC_PV6.0.1_FLASH_TurboRARE_EPI.zip
```

You now have `UNC_PV6.0.1_FLASH_TurboRARE_EPI.zip` in the directory. You will
not unzip it — `pvraw` reads the archive directly.

## 3. Look inside the study

```bash
pvraw info UNC_PV6.0.1_FLASH_TurboRARE_EPI.zip
```

The top of the output is the subject block. Notice that every field says
`None` — this sample ships without a `subject` file, so there is nothing to
show. A study from your scanner fills these in.

Below that is the scan table, one entry per scan:

```
[ScanID]	Sequence::Protocol::[Parameters]
[003]	Bruker:FLASH::1_Localizer_GOP::1_Localizer_GOP (E3)
	[ TR: 100 ms, TE: 3.37 ms, pixelBW: 292.97 Hz, FlipAngle: 30 degree]
    [01] dim: 2D, matrix_size: 256 x 256 x 3, fov_size: 30 x 30 (unit:mm)
         spatial_resol: 0.117 x 0.117 x 3.000 (unit:mm), temporal_resol: 12800.000 (unit:msec)
[006]	Bruker:RARE::CAMRI_T2_RARE_2D_ax::CAMRI_T2_RARE_2D_ax (E6)
	...
```

Read one entry: scan 6 is a RARE sequence, protocol `CAMRI_T2_RARE_2D_ax`, a
2D acquisition of 384 × 384 × 12 voxels at 0.075 × 0.075 × 1 mm. The bracketed
`[01]` is the reconstruction id — a scan can carry more than one
reconstruction, and each converts separately.

## 4. Convert to NIfTI

```bash
pvraw tonii UNC_PV6.0.1_FLASH_TurboRARE_EPI.zip -o first
```

You will see:

```
Identified a localizer, the file will not be converted: ScanID:3
NifTi file is generated... [first-06-1-CAMRI_T2_RARE_2D_ax-(E6)]
NifTi file is generated... [first-07-1-CAMRI_T2_FLASH_2D_cor-(E7)]
NifTi file is generated... [first-10-1-CAMRI_BOLD_EPI_2D]
NifTi file is generated... [first-11-1-CAMRI_BOLD_EPI_2D-(E11)]
```

Notice that the localizer was skipped — positioning scans are not data. The
four `.nii.gz` files in your directory are named
`<prefix>-<ScanID>-<RecoID>-<ProtocolName>`, so a file always traces back to
the scan it came from. Open one in your NIfTI viewer if you have one; the
orientation is already correct.

That is a complete conversion. The rest of the tutorial turns the same study
into a BIDS dataset, which is how you would share it or feed it to analysis
pipelines.

## 5. Propose a BIDS datasheet

BIDS conversion is two commands with your judgement in between: `bids_helper`
proposes a datasheet, you correct it, `bids_convert` follows it.

```bash
pvraw bids_helper . bids_map -j
```

Notice the warning:

```
UserWarning: ScanID:[11] is a single-volume EPI (PVM_NRepetitions<=1), not a
BOLD time-series. Marked as "etc"; set DataType/modality in the datasheet to
convert it.
```

`bids_helper` guesses only what it can defend. Scan 11 uses a functional
sequence but holds a single volume, so it refuses to call it `bold` and marks
it `etc`, which keeps it out of the BIDS tree until you decide. We leave it
that way and see where it ends up in step 8.

Two files appeared: `bids_map.csv`, the datasheet, and `bids_map.json`, a
sidecar-metadata template (we pass it through unchanged).

## 6. Edit the datasheet

Open `bids_map.csv` in your editor. One row per reconstruction (some columns
are elided here for width — your file has more):

```csv
RawData,SubjID,SessID,ScanID,RecoID,DataType,task,acq,...,modality,b0group,Start,End
UNC_PV6.0.1_FLASH_TurboRARE_EPI,None,None,6,1,anat,,,...,,,,
UNC_PV6.0.1_FLASH_TurboRARE_EPI,None,None,7,1,anat,,,...,,,,
UNC_PV6.0.1_FLASH_TurboRARE_EPI,None,None,10,1,fmap,,,...,fieldmap,,0,1
UNC_PV6.0.1_FLASH_TurboRARE_EPI,None,None,10,1,fmap,,,...,magnitude,,1,2
UNC_PV6.0.1_FLASH_TurboRARE_EPI,None,None,11,1,etc,,,...,,,,
```

Make three changes:

1. In every row, replace `None` in the `SubjID` column with `01`, and `None`
   in the `SessID` column with `01`. (They say `None` because the study has no
   `subject` file; yours would prefill.)
2. In the row for scan 6, set the `modality` column to `T2w` — it is a
   T2-weighted RARE.
3. In the row for scan 7, set the `modality` column to `T2starw` — a FLASH at
   this echo time is T2\*-weighted.

Leave everything else exactly as it is, including scan 11's `etc`. Save the
file.

Notice what `bids_helper` had already done: it recognised scan 10 as a
two-echo field map and split it into `fieldmap` and `magnitude` rows using the
`Start`/`End` volume ranges.

## 7. Convert to BIDS

```bash
pvraw bids_convert . bids_map.csv -j bids_map.json -o rawdata
```

Two warnings appear, and both are expected:

- *"acquired in the rodent (quadruped) subject frame ... set the species
  column in participants.tsv"* — ParaVision never records a species name, and
  BIDS reads an absent species as *homo sapiens*. For a dataset you share,
  fill the column in afterwards.
- *"no image follows this fieldmap that it could correct"* — the field map
  would have corrected the EPI, but we left the EPI out of the tree, so the
  field map has nothing to claim.

Then look at what was written:

```bash
find rawdata -type f | sort
```

```
rawdata/CHANGES
rawdata/dataset_description.json
rawdata/participants.json
rawdata/participants.tsv
rawdata/README
rawdata/sourcedata/sub-01/ses-01/sub-01_ses-01_scan-11_reco-1.nii.gz
rawdata/sub-01/ses-01/anat/sub-01_ses-01_T2starw.json
rawdata/sub-01/ses-01/anat/sub-01_ses-01_T2starw.nii.gz
rawdata/sub-01/ses-01/anat/sub-01_ses-01_T2w.json
rawdata/sub-01/ses-01/anat/sub-01_ses-01_T2w.nii.gz
rawdata/sub-01/ses-01/fmap/sub-01_ses-01_fieldmap.json
rawdata/sub-01/ses-01/fmap/sub-01_ses-01_fieldmap.nii.gz
rawdata/sub-01/ses-01/fmap/sub-01_ses-01_magnitude.nii.gz
rawdata/sub-01/ses-01/sub-01_ses-01_scans.tsv
rawdata/sub-01/sub-01_sessions.tsv
```

You have a full BIDS dataset: named and sorted images, JSON sidecars, and the
dataset-level files (`dataset_description.json`, `participants.tsv`, scan and
session tables).

## 8. Find scan 11

Notice `sourcedata/sub-01/ses-01/sub-01_ses-01_scan-11_reco-1.nii.gz`. The
scan we left as `etc` was still converted — it sits outside the validated
tree, named by its scan and reco id, costing no validator errors. Nothing is
silently dropped. To pull it into the dataset proper later, you would set its
`DataType` and `modality` in the datasheet and convert again.

## 9. Validate

Check the result against the BIDS specification, using the same schema
version the converter wrote into `rawdata/dataset_description.json`:

```bash
uvx bids-validator-deno rawdata --schema v1.11.1
```

The report ends with a summary and contains **zero errors** and a handful of
warnings. The warnings ask for information Bruker does not record (author
names, recommended sidecar keys, and the field-map link we chose not to
make). A dataset that validates with zero errors is one any BIDS tool will
accept.

## What you have done

You installed `pvraw`, read a raw ParaVision study without unzipping it,
converted it to NIfTI, and produced a validator-clean BIDS dataset — deciding
yourself what each scan becomes, with the datasheet as the record of those
decisions.

## Where next

- Real studies raise real questions — naming fMRI tasks, linking field maps,
  separating runs, fixing a wrongly recorded subject position. Those are
  covered task by task in
  [How to convert Bruker studies to BIDS](how-to-convert-to-bids.md).
- The [README](../README.md) documents every command-line option and the
  Python API, which hands you the same images as
  [nibabel](https://nipy.org/nibabel/) objects.
