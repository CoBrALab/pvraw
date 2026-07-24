[![made-with-python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg)](https://www.python.org/)

## BrkRaw-legacy: A comprehensive tool to access raw Bruker Biospin MRI data
#### Version: 0.4.0

### About this fork

`brkraw-legacy` is a hard fork of [BrkRaw](https://github.com/BrkRaw/brkraw) that continues the
0.3.x/0.4 line of the project. Upstream BrkRaw has since moved on to a rewritten 0.5+ architecture;
this fork keeps the original, battle-tested converter working on modern Python, with dependency
modernization, BIDS spec compliance work, and bug fixes on top.

It is developed independently of upstream and is **not** a drop-in replacement for it — the
distribution, the import package and the command-line tools are all renamed so the two can be
installed side by side:

|                | upstream BrkRaw | this fork           |
| -------------- | --------------- | ------------------- |
| Distribution   | `brkraw`        | `brkraw-legacy`     |
| Import package | `brkraw`        | `brkraw_legacy`     |
| Conversion CLI | `brkraw`        | `brkraw-legacy`     |

Please report issues with this fork to
[gdevenyi/brkraw-legacy](https://github.com/gdevenyi/brkraw-legacy/issues), not to upstream.

### Description

The ‘BrkRaw-legacy’ is a python module designed to provide a comprehensive tool to access raw data acquired from 
Bruker Biospin preclinical MRI scanner. This module is also compatible with the zip compressed data 
to enable use of the archived data directly.  
The module is comprised of three components, including command-line tools,
high-level and low-level python APIs.
- For the command-line tool, we focused on providing tools for converting, organizing, and managing data.
The command-line tool also provides easy-to-use function to convert large set of raw data into organized structure
according to [BIDS](https://bids.neuroimaging.io).
- For the high-level python API, we focused on enhancing the accessibility of reconstructed image data with 
preserved image orientation and metadata for the image analysis. 
It compatible users' convenient objects type ([nibabel](https://nipy.org/nibabel/)) 
without the conversion step. 
- For the low-level python API, we focused on providing a consistent method to access raw Bruker data including 
parameter and binary files with the python compatible datatype while keeping the sake of simplicity.

A Bruker *PvDataset* can be supplied either as a study directory or as a `.zip`/`.PvDatasets`
archive — every command and API call below accepts both.

---

## Installation

Requires Python >= 3.11.

```bash
pip install git+https://github.com/gdevenyi/brkraw-legacy.git
```

From source (development), using [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/gdevenyi/brkraw-legacy.git
cd brkraw-legacy
uv sync                       # runtime deps, editable install
uv sync --extra dev           # test/lint tooling (pytest, ruff, bids-validator)
```

One command-line tool is installed: **`brkraw-legacy`** (inspection/conversion).

---

## Command-line usage

### Inspect a dataset — `brkraw-legacy info`
Print study/subject info and a table of scans, reconstructions, dimensions and resolutions.

```bash
brkraw-legacy info <input>           # <input> = study dir or .zip
```

### Convert one study — `brkraw-legacy tonii`
Convert a single study to NIfTI. Without `-s` every scan/reconstruction is converted.

```bash
brkraw-legacy tonii <input>                       # convert all scans
brkraw-legacy tonii <input> -s 2 -r 1 -o out      # only ScanID 2, RecoID 1 -> out.nii.gz
```

| Option | Description |
|--------|-------------|
| `-o, --output <name>` | Output filename (without extension) / prefix |
| `-s, --scanid <id>` | Convert a single scan |
| `-r, --recoid <id>` | Reconstruction id (default 1) |
| `-t, --subjecttype <T>` | Override subject type (`Biped`, `Quadruped`, `Phantom`, `Other`, `OtherAnimal`) |
| `-p, --position <P>` | Override position, `<BodyPart>_<Side>` (e.g. `Head_Supine`) |
| `--ignore-rescale` | Write raw stored values, with no intensity scaling in the header. `--ignore-slope` and `--ignore-offset` are aliases: slope and offset cannot be suppressed independently |
| `--ignore-localizer` | Skip localizer/tripilot scans (on by default for `tonii`) |

Non-image scans (spectroscopy, etc.) and unclassifiable scans are skipped with a clear message
rather than producing invalid output. Diffusion scans also emit FSL-style `.bval`/`.bvec`.

### Batch convert — `brkraw-legacy tonii_all`
Convert **every** study under a parent directory into a simple
`sub-<id>/ses-<id>/<datatype>/` tree (`anat`/`func`/`dwi`/`etc`).

```bash
brkraw-legacy tonii_all <parent_dir> -o <output_dir>
```

Accepts the same `-t/-p/--ignore-*` options as `tonii`.

### Convert to BIDS — `brkraw-legacy bids_helper` + `bids_convert`
Produce a spec-compliant [BIDS](https://bids.neuroimaging.io) (v1.10) dataset in two steps:

```bash
# 1. Generate an editable datasheet (+ JSON metadata template with -j)
brkraw-legacy bids_helper <parent_dir> bids_map -j

# 2. Review/fill bids_map.csv (subject, session, datatype, suffix, task, acq, run, ...),
#    then convert using the datasheet and metadata template
brkraw-legacy bids_convert <parent_dir> bids_map.csv -j bids_map.json -o <bids_output>
```

`bids_helper` options: `-f csv|tsv` (datasheet format), `-j` (also write the metadata
template), `-s` (swap subject/study IDs), `-t` (swap session/study ID). `bids_convert`
accepts `-j`, `-o`, and the same `-t/-p/--ignore-*` overrides as `tonii`.

The output is validator-clean: correct filenames/entity ordering, JSON sidecars (with
`TaskName`, units, etc.), `dataset_description.json` (`BIDSVersion` 1.10 + `GeneratedBy`),
`participants.tsv`/`.json`, `README`, `CHANGES`, and a `.bidsignore`. Validate with the
official [bids-validator](https://github.com/bids-standard/bids-validator). Spectroscopic and
unclassifiable scans are skipped rather than written as invalid datatypes.

---

## Python API

> **Changed in 0.5.0.** All Bruker file reading is delegated to
> [`brukerapi`](https://github.com/isi-nmr/brukerapi-python) (see
> `docs/adr/0002-delegate-bruker-reading-to-brukerapi.md`). `study.pvobj` is now a
> `brukerapi` folder rather than a `PvDataset`, the scan/reco listings and subject fields
> moved onto the loader itself, parameter files are `brukerapi` `JCAMPDX` objects, and
> `get_dataobj` returns an array with one named axis per Frame Group.

```python
import brkraw_legacy

study = brkraw_legacy.load('path/to/study_or_archive.zip')   # == BrukerLoader(path)

study.is_pvdataset          # True if a valid PvDataset
study.num_scans             # number of scans
study.info()                # print the same summary as `brkraw-legacy info`

study.avail_scan_id         # e.g. [1, 2, 3, ...]
study.avail_reco_id         # {scan_id: [reco_id, ...]}
study.subj_id, study.study_id, study.session_id

study.pvobj                 # the brukerapi folder the data is read through
```

### Images (high-level)
```python
# nibabel object, orientation + affine preserved
nii = study.get_niftiobj(scan_id=2, reco_id=1)

# write to disk (.nii.gz); save_as is an alias of save_nifti
study.save_nifti(2, 1, 'output_name', dir='.')
study.save_as(2, 1, 'output_name')

# raw ndarray and 4x4 affine
data   = study.get_dataobj(2, 1)
affine = study.get_affine(2, 1)

# one name per axis of that array: ('spatial', 'spatial', 'slice', 'echo', ...)
study.get_axis_labels(2, 1)
study.get_frame_groups(2, 1)   # [('echo', 6), ('slice', 5)]
```
The array carries one axis per ParaVision Frame Group, named. Multi-slice-package or
multi-echo scans return a **list** of images; `save_nifti` writes them as
`name-01.nii.gz`, `name-02.nii.gz`, ....

### Parameters (low-level)
```python
from brkraw_legacy.lib.utils import get_value

method = study.get_method(2)            # method file  (a brukerapi JCAMPDX)
acqp   = study.get_acqp(2)              # acqp file
visu   = study.get_visu_pars(2, 1)      # visu_pars (per reconstruction)

get_value(method, 'Method')             # any parameter by key
get_value(acqp, 'ACQ_size')
get_value(visu, 'NotThere', default=0)  # absence is version-dependent; default it
```
`get_value` resolves the JCAMP-DX representation -- it unwraps `<...>` string literals,
returns a struct array as a list of rows, and returns `default` for an absent key
(which `brukerapi`'s own `get_value` raises on).

### Diffusion
```python
bvals, bvecs = study.get_bdata(scan_id)     # FSL-style arrays
study.save_bdata(scan_id, 'dwi', dir='.')   # writes dwi.bval / dwi.bvec
```

### Overrides
```python
study.override_subjtype('Quadruped')        # fix mis-set subject type
study.override_position('Head_Supine')       # fix mis-set position
```

---

#### Conversion reliability
![Robust Orientation](imgs/bruker2nifti_qa.png)
We've tested our converter using the sample dataset from [Bruker2Nifti_QA](https://gitlab.com/naveau/bruker2nifti_qa) 
and the results showed correct geometry and orientation for all datasets.
We are still looking for more datasets showing orientation issue, 
**if you have any shareable dataset, please contact the developer.**

### Website
The upstream documentation for the 0.3.x line still broadly applies to this fork — substitute
`brkraw-legacy` wherever it says `brkraw`:

- [Installation](https://brkraw.github.io/docs/gs_inst.html)
- [Command-line tool usage examples](https://brkraw.github.io/docs/gs_nii.html)
- [Converting dataset into BIDS](https://brkraw.github.io/docs/gs_bids.html)
- [Python API usage examples](https://brkraw.github.io/docs/ap_parent.html)
- [Interactive Tutorial](https://mybinder.org/v2/gh/BrkRaw/tutorials/ac95b2c87b05664cb678c5dc1a930641397130ed)


### Credits:
##### Authors of the original BrkRaw project
- SungHo Lee (shlee@unc.edu): main developer
- Woomi Ban (banwoomi@unc.edu): sub-developer who tested and refined the module structure
- Jaiden Dumas: proofreading of documents and update contents for the user community.
- Dr. Gabriel A. Devenyi: The vast contributions to refinement of module functionality and troubleshooting.
- Yen-Yu Ian Shih (shihy@neurology.unc.edu): technical and academical advisory on this project (as well as funding)
##### Maintainer of this fork
- Dr. Gabriel A. Devenyi (gdevenyi@gmail.com)
##### Contributors
- Drs. Chris Rorden and Sebastiano Ferraris: The pioneers related this project who had been inspired the developer
 through their great tools including [dcm2niix](https://github.com/rordenlab/dcm2niix) and 
 [bruker2nifti](https://github.com/SebastianoF/bruker2nifti), as well as their comments to improve this project. 
- Dr. Mikael Naveau: The publisher of 
[bruker2nifti_qa](https://gitlab.com/naveau/bruker2nifti_qa), the set of data 
to help benchmark testing of Bruker converter.


### License:
GNU General Public License v3.0

### How to get Support
If you are experiencing any problem or have questions about **this fork**, please report it through 
[Issues](https://github.com/gdevenyi/brkraw-legacy/issues).

### Citing BrkRaw
This fork builds on the original BrkRaw project; please cite the original work:

[![DOI](https://zenodo.org/badge/245546149.svg)](https://zenodo.org/badge/latestdoi/245546149)

Lee, Sung-Ho, Ban, Woomi, & Shih, Yen-Yu Ian. (2020, June 4). BrkRaw/bruker: BrkRaw v0.3.3 (Version 0.3.3). 
Zenodo. http://doi.org/10.5281/zenodo.3877179


**BibTeX**
```
@software{lee_sung_ho_2020_3907018,
  author       = {Lee, Sung-Ho and
                  Ban, Woomi and
                  Shih, Yen-Yu Ian},
  title        = {BrkRaw/bruker: BrkRaw v0.3.4},
  month        = jun,
  year         = 2020,
  publisher    = {Zenodo},
  version      = {0.3.4},
  doi          = {10.5281/zenodo.3907018},
  url          = {https://doi.org/10.5281/zenodo.3907018}
}
```
