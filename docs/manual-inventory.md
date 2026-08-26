# ParaVision Manual Inventory

This inventory records the local sources available for auditing `FILE_FORMAT.md`. The
`manuals/` tree is intentionally ignored by Git; paths below therefore describe the shared local
workspace and may need to be restored separately in a fresh clone.

Inventory refreshed: 2026-08-26. At that point `manuals/` contained 676 PDF files and 11,983
non-PDF files, including installed documentation trees, course material, headers, and sample
datasets.

## Source priority

For a claim about a specific ParaVision release, use sources in this order:

1. That release's file-format or complete user manual.
2. That release's parameter-reference, reconstruction, or programming manual.
3. C headers and other installed developer documentation from the same release.
4. Bundled datasets from the same release, explicitly labelled as on-disk observation.
5. Manuals or datasets from another release, explicitly labelled as cross-version evidence.

Do not silently generalize a fact from one version to another. Record claims as manual-verified,
header-verified, observed, derived, contradicted, or unresolved.

## Primary sources by version

### ParaVision 5.1

- `manuals/pv5/pvman/D/Docs/D12_FileFormats.pdf` — file layout, JCAMP-DX, `fid`, and `2dseq`.
- `manuals/pv5/pvman/D/Docs/D13_PvParams.pdf` — parameter reference.
- `manuals/pv5/pvman/D/Docs/D07_ImageReco.pdf` — image reconstruction.
- `manuals/pv5/pvman/D/Docs/D05_BasLevAcq.pdf` — base-level acquisition.
- `manuals/pv5/pvman/D/Docs/D08_MethodProg.pdf` — method programming.
- `manuals/pv5/xwinproc/pdf/fileform.pdf` — XWIN-NMR/TopSpin binary and parameter formats.
- `manuals/pv5/pvman/D/Docs/` — remaining programming and configuration manuals.

### ParaVision 6.x

- `manuals/pv6/pvman/D/Docs/D01_FileFormats.pdf` — file layout, JCAMP-DX, `fid`, job data, and
  `2dseq`.
- `manuals/pv6/pvman/D/Docs/D02_PvParams.pdf` — parameter reference.
- `manuals/pv6/pvman/ParaVision_6.0/ParaVision_6.0_en_536169227.pdf` — complete PV6.0 manual.
- `manuals/pv6/pvman/ParaVision_6.0.1/ParaVision_6.0.1_en_638260747.pdf` — complete PV6.0.1
  manual.
- `manuals/pv6/xwinproc/pdf/fileform.pdf` — XWIN-NMR/TopSpin file format.
- `manuals/course_pulseq_prog_PV6_2014/PV6_Manual_MethodProgramming.pdf` — PV6 method
  programming course reference.
- `manuals/course_pulseq_prog_PV6_2014/12 Image reconstruction.pdf` — reconstruction course
  material.
- `manuals/course_pulseq_prog_PV601_2016/` — later PV6.0.1 programming course material.

The `_z`, `_zs`, `_zs2`, `_zs3`, `_zsf`, and similarly suffixed PDFs are duplicate or
OCR/searchability variants. Prefer the unsuffixed source unless its text layer is unusable.

### ParaVision 7

- `manuals/pv7/pvman/ParaVision/Pv7Manual.pdf` — complete PV7 manual; includes Programming &
  Administration, Data Formats §3.3, and parameter documentation.
- `manuals/pv7/pvman/ParaVision/PvManual.pdf` — alternate installed complete-manual build;
  compare metadata/content before treating it as an independent edition.
- `manuals/pv7/topspin/pdf/fileform.pdf` and `manuals/pv7/xwinproc/pdf/fileform.pdf` — TopSpin
  file-format copies.
- `manuals/pv7/AutomaticDicomExport7.0.pdf`, `manuals/pv7/first_steps_readme.pdf`, and
  `manuals/pv7/first_steps_readme3.6.pdf` — focused supplementary documents.

### ParaVision 360

Complete user manuals are available for the following releases:

| Release | Local source |
|---------|--------------|
| 1.0 | `manuals/User_Manual_PV360_V1.0 (1).pdf` |
| 1.1 | `manuals/User_Manual_PV360_V1.1.pdf` |
| 2.0 | `manuals/User_Manual_PV360_V2.0.pdf` |
| 3.0 | `manuals/User_Manual_PV360_V3.0.pdf` |
| 3.1 | `manuals/User_Manual_PV360_V3.1.pdf` |
| 3.2 | `manuals/User_Manual_PV360_V3.2.pdf` |
| 3.3 | `manuals/User_Manual_PV360_V3.3.pdf` |
| 3.4 | `manuals/User_Manual_PV360_V3.4.pdf` |
| 3.5 | `manuals/User_Manual_PV360_V3.5.pdf` |
| 3.6 | `manuals/PV360-3.6/pvman/Manual.pdf` |
| 3.7 | `manuals/PV-360-3.7/ManualPv360V3.7.pdf` |

Additional PV360 sources:

- `manuals/pv360/Bruker-Manual-Complete-.pdf` — older complete-manual bundle; establish its
  edition from internal metadata before citing it.
- `manuals/PV-360-3.7/Distribution_Note_and_Installation_GuidePv360V3.7.pdf` and
  `manuals/pv360/Distribution_Note_and_Installation_Guide.pdf` — installation/distribution
  notes.
- `manuals/PV360-3.6/topspin/` — TopSpin documentation shipped with PV360 3.6.

Data Formats moves between chapters across the series. Search for the `Dataset Paths` heading
rather than assuming the PV360 3.6/3.7 section number §4.12.1.

## Course material and bundled datasets

- `manuals/course_pulseq_prog_PV5_2013/` — PV5 programming course, example methods, headers,
  and training notes.
- `manuals/course_pulseq_prog_PV6_2014/` — PV6 programming course, installed HTML docs,
  source examples, headers, and real PV6 course datasets under `ppc2014_data/data/`.
- `manuals/course_pulseq_prog_PV601_2016/` — PV6.0.1 programming course material.

Bundled datasets are valuable for verifying exact on-disk spelling, optional files, struct
arity, wrapping, and serialization. They are observational evidence, not a substitute for a
manual's normative description.

## Useful extraction commands

Extract one manual while preserving approximate page layout:

```bash
pdftotext -layout path/to/manual.pdf /tmp/manual.txt
```

Locate the format chapters after extraction:

```bash
rg -n -i 'Dataset Paths|Parameter Files|Raw Data Files|Image Data Files' /tmp/manual.txt
```

Inventory primary format/reference sources:

```bash
find manuals -type f | rg -i '/(D01_FileFormats|D02_PvParams|D07_ImageReco|D12_FileFormats|D13_PvParams|fileform|Pv7Manual|User_Manual_PV360).*\.pdf$'
```

Use PDF page numbers and the manual's printed page labels carefully: introductory pages can make
them differ. When possible, cite the chapter/section, table number, and printed page label
together.

