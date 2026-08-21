# ADR 0003: The BIDS session is ParaVision's session number, read from the study directory name

- Status: Accepted
- Date: 2026-08-21

Since ParaVision 6 the dataset levels are Project → Subject → Session → Study →
Examination → Image Series: the Session is the visit, and a Study is one dataset
directory created from a study template (PV6.0.1 Operating Manual 1.7.4, p. 214;
PV360 V3.7 manual p. 41, 441). `SUBJECT_study_nr` is the study's number inside its
session — the template slot — and no parameter file carries the session number: the
dataset server writes it only into the directory name, as
`<$Date>_<$Time>_<$AnimalID>_<session>_<study>` (or Animal ID first, per the "Study
Directory Pattern" option), then replaces every non-word character by `_`
(`de.bruker.mri.dsetserver.util.NeedFulThings.buildStudyPath`, PV6.0.1). pvraw
therefore takes the BIDS session from the second-last `_` field of the study
directory name and keeps `SUBJECT_study_nr` as the study number. This is a
deliberate exception to FILE_FORMAT.md's rule not to read meaning out of the name.
A name without the suffix (PV5, a renamed directory) falls back to
`SUBJECT_study_nr`, the previous behaviour: PV5 has no sessions, and there a study
is one visit.

## Considered options

- `SUBJECT_study_nr` (the previous choice): in the file and safe against renames,
  but it is the template slot — every visit of a longitudinal project gets the same
  value, and two templates run in one visit get two different ones.
- The study date: unique per study, but two studies of one visit become two
  sessions, and a timestamp is a poor session label.
- The directory name (chosen): the only on-disk carrier of the session.

## Consequences

- A subject with several studies in the Default session (no project) now gets one
  `ses-1` where it previously got `ses-1` … `ses-N`. ParaVision says they are one
  session. A filename collision across those studies is refused by `bids_convert`
  instead of overwritten; `run-` disambiguates.
- The session name and the project exist only in the ParaVision database.
  Export the Dataset Browser table (with the project and session columns)
  together with the data.
