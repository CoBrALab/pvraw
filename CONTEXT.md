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

## Subject framing

**Declared Position**:
The position ParaVision was told the subject was in — `VisuSubjectPosition`
(`ACQ_patient_pos`), e.g. `Head_Supine` — and therefore the frame it writes
its geometry in. Often the untouched default.
_Avoid_: recorded position, patient position, pose

**Actual Position**:
How the subject really lay in the cradle: what `-p/--position` states and what
the output is framed for. Assumed `Head_Prone` (prone, head first) when not
stated.
_Avoid_: override position, corrected position

## Subject and study identity

The `subject` file names three people-ish things and one of them is the
subject. `pvraw info` and `info_dict()` use the names below; FILE_FORMAT.md
section 9 carries the per-version parameter spellings.

Since brukerapi 0.4.6 the Subject ID, Study Name, Study Nr and study date in
`info_dict()` read through `brukerapi`'s Dataset properties (`subj_id`,
`study_id`, `study_nr`, `date` — the `Visu*` spellings, ADR 0002) from the
first readable reconstruction; the subject-file reads below are the fallback
for a study with no readable reconstruction. Subject Name, Operator and User
Account have no brukerapi property and stay subject-file reads.

**Subject Name**:
The subject's own name, `SUBJECT_name_string` (DICOM patient-name format on
PV360: `family^given^middle^prefix^suffix`). `subject_name` in `info_dict()`.
_Avoid_: researcher, user name, patient name

**Subject ID**:
The user-defined identifier of the subject, `SUBJECT_id`; what `sub-` is built
from. `subject_id` in `info_dict()`.
_Avoid_: study id, id

**Operator**:
The person entered at study registration: `SUBJECT_study_operator` (PV360),
`SUBJECT_referral` before it. `operator` in `info_dict()`.
_Avoid_: researcher, referring physician, owner

**User Account**:
The login that wrote the study: the JCAMP `##OWNER`, equal to `ACQ_operator`.
Not the Operator -- on a shared console they differ. `user_account` in
`info_dict()`.
_Avoid_: operator, owner, user

**Study Name**:
The user-given name of the study, `SUBJECT_study_name` (`VisuStudyId`).
`study_name` in `info_dict()`; the loader's `study_id` property returns it.
_Avoid_: study id, session name
