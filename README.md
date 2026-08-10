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

Requires Python >= 3.11. Everything here uses [uv](https://docs.astral.sh/uv/), which
manages the interpreter and the dependencies for you — there is no separate virtualenv
to create or activate.

**As a command-line tool.** Installs `brkraw-legacy` onto your `PATH`, isolated from
your other environments:

```bash
uv tool install git+https://github.com/gdevenyi/brkraw-legacy.git
uv tool upgrade brkraw-legacy      # later, to update
```

**As a dependency of your own project**, for the Python API:

```bash
uv add git+https://github.com/gdevenyi/brkraw-legacy.git
```

**From source**, for development or to run an unreleased change:

```bash
git clone https://github.com/gdevenyi/brkraw-legacy.git
cd brkraw-legacy
uv sync                       # runtime deps, editable install
uv sync --extra dev           # also pytest, ruff and bids-validator
```

One command-line tool is installed: **`brkraw-legacy`** (inspection/conversion).

> The examples below are written as `uv run brkraw-legacy ...`, which works from a
> source checkout. If you installed with `uv tool install`, drop the `uv run` prefix.

---

## Command-line usage

### Inspect a dataset — `brkraw-legacy info`
Print study/subject info and a table of scans, reconstructions, dimensions and resolutions.

```bash
uv run brkraw-legacy info <input>           # <input> = study dir or .zip
```

### Convert one study — `brkraw-legacy tonii`
Convert a single study to NIfTI. Without `-s` every scan/reconstruction is converted.

```bash
uv run brkraw-legacy tonii <input>                       # convert all scans
uv run brkraw-legacy tonii <input> -s 2 -r 1 -o out      # only ScanID 2, RecoID 1
uv run brkraw-legacy tonii <input> -s 2,3,7 -r 1,2       # several scans, several recos
```

Each file is named `<output>-<ScanID>-<RecoID>-<ProtocolName>.nii.gz`, so `-o` sets the
prefix rather than the whole filename — one scan can write several files (a multi-echo
or multi-slicepack reconstruction writes one per echo or pack).

| Option | Description | Default |
|--------|-------------|---------|
| `-o, --output <name>` | Output filename (without extension) / prefix | `<SubjID>_<StudyID>`, or the input folder name when the dataset has no subject file |
| `-s, --scanid <id[,id...]>` | Convert only the listed scans | every scan |
| `-r, --recoid <id[,id...]>` | Reconstruction ids; only read together with `-s`, since without it every reconstruction is converted | `1` |
| `-b, --bids` | Also write a JSON sidecar of BIDS-recommended metadata | off |
| `-t, --subjecttype <T>` | Override subject type (`Biped`, `Quadruped`, `Phantom`, `Other`, `OtherAnimal`) | the recorded subject type |
| `-p, --position <P>` | Override position, `<BodyPart>_<Side>` (e.g. `Head_Supine`) | the recorded position |
| `--ignore-rescale` | Write raw stored values, with no intensity scaling in the header. `--ignore-slope` and `--ignore-offset` are aliases: slope and offset cannot be suppressed independently | off (the header carries the scaling) |
| `--ignore-localizer` | Skip localizer/tripilot scans | on |

Every on/off option also has a `--no-` form — `--no-bids`, `--no-ignore-localizer`,
`--no-ignore-rescale` — so a default that is on can be turned off from the command line.

Non-image scans (spectroscopy, etc.) and unclassifiable scans are skipped with a clear message
rather than producing invalid output. Diffusion scans also emit FSL-style `.bval`/`.bvec`.

### Batch convert — `brkraw-legacy tonii_all`
Convert **every** study under a parent directory into a simple
`sub-<id>/ses-<id>/<datatype>/` tree (`anat`/`func`/`dwi`/`etc`).

```bash
uv run brkraw-legacy tonii_all <parent_dir> -o <output_dir>
```

Accepts the same `-b/-t/-p/--ignore-*` options as `tonii`, with the same defaults.
Without `-o` the tree is written to `Data` in the current directory.

### Convert to BIDS — `brkraw-legacy bids_helper` + `bids_convert`
Produce a spec-compliant [BIDS](https://bids.neuroimaging.io) dataset in two steps:

```bash
# 1. Generate an editable datasheet (+ JSON metadata template with -j)
uv run brkraw-legacy bids_helper <parent_dir> bids_map -j

# 2. Review/fill bids_map.csv (subject, session, datatype, suffix, task, acq, run, ...),
#    then convert using the datasheet and metadata template
uv run brkraw-legacy bids_convert <parent_dir> bids_map.csv -j bids_map.json -o <bids_output>
```

`bids_helper` options: `-f csv|tsv` (datasheet format, default `csv`, ignored when
`output` already ends in `.csv`/`.tsv`), `-j` (also write the metadata template, default
off), `--subj` (swap subject/study IDs, default off), `--sess` (swap session/study ID,
default off). Those last two have no short form on purpose: `-s` and `-t` mean
`--scanid` and `--subjecttype` elsewhere. `bids_convert` accepts `-j <template>` (default: none, so the sidecars carry only
what the converter derives), `-o <dir>` (default: `Data`), and the same
`-t/-p/--ignore-*` overrides as `tonii`. It converts exactly what the datasheet lists,
so it has no `--ignore-localizer`: `bids_helper` already leaves localizers out.

Step 2 is where the work is: what to put in the datasheet, what to do about scans
marked `etc`, how to name a task, how to link a fieldmap to the images it corrects, and
what the validator warnings mean are all covered in
**[How to convert Bruker studies to BIDS](docs/how-to-convert-to-bids.md)**.

The output is validator-clean: correct filenames and entity ordering, JSON sidecars,
`dataset_description.json`, `participants.tsv`/`.json`, `<subject>_sessions.tsv`,
`<subject>_scans.tsv` with acquisition times, `README` and `CHANGES`. `anat`, `func`,
`dwi`, `fmap` and `perf` (ASL, with its `aslcontext.tsv`) are emitted, and fieldmaps are
linked to the images they correct via `B0FieldIdentifier` and `IntendedFor`.

`BIDSVersion` is taken from the BIDS schema the converter validates against, so the two
can never disagree. Validate with the official
[bids-validator](https://github.com/bids-standard/bids-validator).

Nothing is silently dropped. A ParaVision-computed stack with no single BIDS suffix (a
DTI tensor reconstruction) goes to `derivatives/brkraw-legacy/`, and a scan that cannot
be classified goes to `sourcedata/` — both outside the validated tree, so the data is
kept without costing an error.

---

## Python API

> **Changed in 0.5.0.** All Bruker file reading is delegated to
> [`brukerapi`](https://github.com/isi-nmr/brukerapi-python) (see
> `docs/adr/0002-delegate-bruker-reading-to-brukerapi.md`). `study.pvobj` is now a
> `brukerapi` folder rather than a `PvDataset`, the scan/reco listings and subject fields
> moved onto the loader itself, parameter files are `brukerapi` `JCAMPDX` objects, and
> `get_dataobj` returns an array with one named axis per Frame Group -- which is also the
> shape `brkraw-legacy info` prints, where it used to print a collapsed matrix size.
>
> Requires `brukerapi>=0.4.3`, which supplies the voxel-to-patient affine
> (`affine_of_package`), the slice-package division and the slice spacing
> (`slice_distance`), and which returns JCAMP-DX string values without their
> `<...>` delimiters. Earlier releases either lack those or place volumes
> wrongly.

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

## Development

From a source checkout, after `uv sync --extra dev`:

```bash
uv run pytest                        # everything; sample data is fetched from the network
uv run pytest -m "not data"          # offline unit tests only, no downloads
uv run pytest tests/08_orientation_test.py    # a single file

uv run ruff check .                  # must be clean
uv run ruff check . --fix            # safe fixes only -- then re-run the tests
```

Data-dependent tests download public sample studies (Zenodo, GitHub) and cache them under
`$BRKRAW_TEST_DATA_DIR`. Set it to keep the cache between runs:

```bash
BRKRAW_TEST_DATA_DIR=~/.cache/brkraw-test-data uv run pytest -m data
```

Two sweep tools compare a whole corpus before and after a change, which is how geometry and
BIDS regressions get caught:

```bash
uv run python tools/sweep_nifti.py <corpus_dir>              # affines, data hashes, headers
uv run python tools/sweep_nifti.py <corpus_dir> --compare=<earlier.json>
uv run python tools/sweep_bids.py                            # convert + validate every study
```

CI installs from `uv.lock` with `uv sync --locked`, so every tool version is pinned and a new
ruff or pytest release cannot break an unrelated change. `--locked` also fails if
`pyproject.toml` was edited without re-running `uv lock`.

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
