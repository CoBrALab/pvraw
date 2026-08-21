# pvraw

Converts raw Bruker Biospin preclinical MRI data into NIfTI and BIDS. The domain
spans three vocabularies for the same things — Bruker's own (ParaVision manuals
and headers), brukerapi's (TopSpin lineage), and pvraw's. This glossary picks
one of each and names the others so they don't drift back together.

## Dataset structure

**PvDataset**:
One ParaVision study of raw output, supplied either as a study directory or as
a `.zip`/`.PvDatasets` archive of it. The unit a user hands to the CLI.
_Avoid_: dataset, session folder, raw data

**Session**:
One visit of a subject: ParaVision's session level, numbered per subject, which
BIDS calls `ses-`. A Session holds one Study per study template that was run.
_Avoid_: visit, timepoint, study number

**Study**:
The top level of a PvDataset — one ParaVision study: one subject, one Session,
one study template, containing many Scans.
_Avoid_: subject, session, experiment

**Study Number**:
ParaVision's number of a Study inside its Session (`SUBJECT_study_nr`); under a
project, the study-template slot. Not the Session.
_Avoid_: session number, session id

**Scan**:
A single acquisition within a Study, holding the raw FID plus its acquisition
and method parameters. Addressed by `scan_id` (`-s/--scanid`).
_Avoid_: Experiment, EXPNO, exp_id, series

**Reco**:
One reconstruction of a Scan, holding the reconstructed image and its
visualisation parameters. A Scan may have several. Addressed by `reco_id`
(`-r/--recoid`).
_Avoid_: Processing, PROCNO, proc_id, reconstruction number

> `Experiment`/`Processing` and `exp_id`/`proc_id` are brukerapi's names for Scan
> and Reco; `EXPNO`/`PROCNO` are Bruker's. They are correct in their own contexts
> and must not leak into ours — translate at the boundary.

## Image structure

**Frame Group**:
A non-spatial axis of a Reco's image, named by ParaVision — `FG_SLICE`,
`FG_ECHO`, `FG_MOVIE`, `FG_DIFFUSION` and so on. What distinguishes a multi-echo
volume from a time series from a diffusion series.
_Avoid_: dimension, frame axis, extra dim

**Frame**:
One 2D or 3D image at a single position in every Frame Group. The unit that
slope and offset scaling applies to.
_Avoid_: volume, slice, image

**Slice Package**:
A group of slices sharing one geometry within a Reco. More than one means the
Reco has multiple distinct orientations and cannot be a single NIfTI.
_Avoid_: slab, slice group, stack
