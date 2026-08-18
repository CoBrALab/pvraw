# pvraw

Converts raw Bruker Biospin preclinical MRI data into NIfTI and BIDS. The domain
spans three vocabularies for the same things — Bruker's own (ParaVision manuals
and headers), brukerapi's (TopSpin lineage), and pvraw's. This glossary picks
one of each and names the others so they don't drift back together.

## Dataset structure

**PvDataset**:
One subject-session of raw ParaVision output, supplied either as a study
directory or as a `.zip`/`.PvDatasets` archive. The unit a user hands to the CLI.
_Avoid_: dataset, session folder, raw data

**Study**:
The top level of a PvDataset — one subject scanned on one occasion, containing
many Scans.
_Avoid_: subject, session, experiment

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
