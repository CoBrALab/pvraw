# Datasets

Publicly available Bruker/ParaVision datasets used with **pvraw** — in the
automated test suite and/or for manual validation during development.

None of the raw data is committed to this repository. The test suite fetches what
it needs from public sources at runtime (see `tests/conftest.py`), and any locally
cached validation data lives under the git-ignored `resources/testdata/` directory.

> **Licensing:** always check each dataset's own license before redistributing or
> using it commercially. Where a restriction is known it is noted below; where it
> is blank, consult the source. pvraw does not re-host any of this data.

## Used by the test suite

The `tests/conftest.py` fixtures fetch the phantom studies on demand (cached under
`$PVRAW_TEST_DATA_DIR`; `data`-marked tests skip if the source is unreachable).

| Dataset | ParaVision | Source | Notes |
|---|---|---|---|
| `0.2H2` | PV5.1 | [zenodo.org/records/4048286](https://zenodo.org/records/4048286) (`0.2H2.zip`) | Multi-sequence phantom study, 32 experiments. `h2_study` fixture. |
| `lego_phantom` | PV6.0.1 | [zenodo.org/records/4048253](https://zenodo.org/records/4048253) (`20200612_094625_lego_phantom_3_1_2.zip`) | Multi-sequence phantom study, 45 experiments. `lego_study` fixture; also the loader↔API parity and handle-leak tests. |
| `LEGO_PHANTOM_API_TEST` | PV7.0.0 | [zenodo.org/records/4522220](https://zenodo.org/records/4522220) (`20210128_122257_LEGO_PHANTOM_API_TEST_1_1.zip`, 618 MB) | Multi-sequence phantom study, 39 experiments (B1Map, CPMG, CSI, DESS, FLASH, RARE, EPI, UTE, …). `pv7_study` fixture; also `dataset[2]` in the loader sweep. Converts cleanly through pvraw: **30 image scans → NIfTI, 12 spectroscopic rejected cleanly, 0 failures**. Notes: PV7.0.0 uses `VisuVersion=3` (same as PV6); adds a `pdata/*/pvmeta` JCAMP file; the `fid.npz` files are NumPy arrays added by the BrukerAPI project, not native Bruker. |
| `PV360_StdData` | PV360 v3.6 | [github.com/cecilyen/PV360_StdData](https://github.com/cecilyen/PV360_StdData) (git-LFS) | Loose scan collection (no `subject` file). `pv360_root` fixture; standalone-scan and non-PvDataset tests. |
| `brkraw-dataset` (UNC) | PV5.1, PV6.0.1 | [github.com/BrkRaw/brkraw-dataset](https://github.com/BrkRaw/brkraw-dataset) (git-LFS) | BrkRaw's own example data: `PV5.1/UNC_PV5.1_BOLD-EPI_TurboRARE.zip`, `PV6.0.1/UNC_PV6.0.1_FLASH_TurboRARE_EPI.zip`. Cloned to `testdata/brkraw-dataset/` — both zips convert cleanly in the full sweep. |

`0.2H2`, `lego_phantom` and `LEGO_PHANTOM_API_TEST` are the
[BrukerAPI](https://github.com/isi-nmr/brukerapi-python) project's public test data. The
consolidated record [zenodo.org/records/4522220](https://zenodo.org/records/4522220) bundles all
three (`0.2H2.zip` PV5.1, `20200612_..._lego_phantom_...zip` PV6.0.1, and the
`20210128_..._LEGO_PHANTOM_API_TEST_...zip` PV7.0.0 study); the PV5.1/PV6.0.1 studies are also
available as the standalone records 4048286 / 4048253 used by the older fixtures.

## Used for local validation (git-ignored `resources/testdata/`)

Public datasets pulled locally to develop or verify a change; not part of CI.

| Dataset | ParaVision | Source | License | Notes |
|---|---|---|---|---|
| `bruker2nifti_qa` | PV5/6 | [gitlab.com/naveau/bruker2nifti_qa](https://gitlab.com/naveau/bruker2nifti_qa) (git-LFS) | see repo | Materialized at `testdata/bruker2nifti_qa/` (~340 MB LFS): 4 studies — Cyceron_DWI, Cyceron_MultiEcho, McGill_Orientation (×2). Source of the `cyceron_*` header stubs in `pv6/headers/`. Converts in the full sweep; a couple of derived DWI reconstructions fail on a missing `VisuAcqGradEncoding`. |
| MRIReco.jl test data | PV6.0.1 + PV360 V3.4 | [media.tuhh.de/ibi/mrireco/MRIRecoTestData.tar.gz](http://media.tuhh.de/ibi/mrireco/MRIRecoTestData.tar.gz) (`sha256 c5a421aab7f3ea3fb20c469704db33c17b659861d9d77dbd29e353db2d5c8fc7`) | see MRIReco.jl | Bruker scans: 2D/3D FLASH, 2D RARE, 3D UTE (radial + traj), PV360 CS FLASH. Surfaced/validated the headerless-`2dseq`, single-slice→3D, per-reco-params, and handle-leak fixes. |
| Aswendt GFAP PT 4wks | PV6.0.1 | [gin.g-node.org/Aswendt_Lab/2021_Aswendt_GFAP_PT_4wks](https://gin.g-node.org/Aswendt_Lab/2021_Aswendt_GFAP_PT_4wks) — DOI [10.12751/g-node.yzjhz3](https://doi.gin.g-node.org/10.12751/g-node.yzjhz3) | **CC BY-NC-SA 4.0** | Longitudinal mouse stroke study (raw Bruker + processed NIfTI), 82 GiB total via git-annex. One study pulled via GIN `/raw/` for validation; exposed the dangling-symlink `_fetch_dir` crash. NonCommercial → not suitable as a CI fixture. |
| PCI Standard Datasets | PV360 3.5 / 3.6 / 3.7 | Bruker download table ([login-gated page](https://www.bruker.com/protected/en/services/communities/pci-community/paravision-versions/paravision-standard-datasets.html); forum thread [988](https://pci-community.com/t/standard-datasets-for-pv360-3-5-3-6/988)) | **Bruker login; NOT re-hostable** — Bruker legal has not approved public mirroring ("please refrain from uploading the data to other servers") | 35 datasets on an ex-vivo mouse-head phantom: FLASH 2D/3D/iso, RARE T1/T2, MSME, MGE (positive & all echoes), EPI, DTI (30-dir, single & multi-shell), 3D UTE, PRESS. Downloaded to git-ignored `testdata/bruker_pv360_standard/` (2.1 GB, one `.PvDatasets` each). All 35 convert; surfaced the single-slice ISA parametric-map affine bug (fixed in #31). |

> Local, non-public acquisitions under `resources/testdata/` — `pv6/full/mch_dev_022` and
> `new-orientation/` (CIC phantom / plantest studies) — are intentionally omitted:
> they have no public source.

### Raw ParaVision datasets from Zenodo (conversion-sweep coverage)

Public **raw** Bruker/ParaVision datasets found by querying the
[Zenodo REST API](https://developers.zenodo.org/) for ParaVision / preclinical-MRI
raw data (filtering out the far more numerous Bruker NMR, crystallography and
mass-spec records, and the many "Bruker MRI" records that only ship *derived*
NIfTI/MINC). Downloaded under the git-ignored `resources/testdata/zenodo/<slug>/`
and run through the full NIfTI + BIDS conversion sweep (`tools/sweep_nifti.py`,
`tools/sweep_bids.py`). Together they extend coverage to mouse/rat/**lemur**,
fields from 7T to 9.4T, PV5.1/6.0/6.0.1/7.0.0, and acquisition types (opto-fMRI,
multishell DWI, DCE, CSI, quantitative T2/DTI maps) well beyond the phantom
fixtures. The sweep surfaced several conversion bugs, each fixed in its own PR.

| Dataset | ParaVision | Source (Zenodo) | License | Conversion notes |
|---|---|---|---|---|
| SAMRI test data | PV6.0 | [3823441](https://zenodo.org/records/3823441) (`samri_bindata-0.4.tar.xz`, 2.3 GB) | CC-BY-4.0 | Mouse, rat & **lemur**; BOLD / seEPI / geEPI / TurboRARE. 45 image scans, all convert. Surfaced the `SoftwareVersions` sidecar-schema flag (fixed in #42). |
| DHMC opto-fMRI | PV6.0.1 | [13688071](https://zenodo.org/records/13688071) (`dhmcps_brudata-0.1.tar.xz`, 385 MB) | CC-BY-4.0 | Explicit "raw Bruker ParaVision" opto-fMRI pilot; ~20 sessions (phantoms + FC000x). 180 scans, all convert cleanly. |
| Optic-pathway dMRI | PV6.0.1 | [8120834](https://zenodo.org/records/8120834) (`mouse02`+`mouse09.tar.gz`, 2 of 18 mice) | not stated | 7T multishell DWI EPI (60-dir, b∈{250,1000,2250,4000}) + 100µm FLASH T1. Surfaced the method-less-scan `bids_helper` KeyError (`mouse09/followup` scan 4, fixed in #39). |
| Rat stroke T2 (SAHA) | PV5.1 (7T) | [20933774](https://zenodo.org/records/20933774) (zip, 1.6 GB) | CC-BY-4.0 | 24 SHR-rat sessions, quantitative T2. Raw T2 (reco 1) converts; the 24 derived T2 maps (reco 2) surfaced the `FG_ISA` derived-recon parser bug (fixed in #37). |
| DCE-MRI FUS BBB | PV7.0.0 (9.4T) | [13683103](https://zenodo.org/records/13683103) (`ISIBrno_FUS_DCEMRI_v2.zip`, 4.1 GB) | CC-BY-4.0 | 3D FLASH GASOS DCE + IRLL, 11 mouse studies (63 scans). All convert cleanly. |
| HP ¹³C static CSI | PV7.0.0 (7T) | [20429962](https://zenodo.org/records/20429962) (zip, 29 MB) | CC-BY-4.0 | Hyperpolarized ¹³C-pyruvate mouse abdomen. Image scans convert; CSI spectroscopic frames cleanly rejected (no crash). |
| Operando thermocell | PV6-era | [5565584](https://zenodo.org/records/5565584) (zip, 260 MB) | CC-BY-4.0 | Electrochemical-cell MRI (temperature/redox maps), 939 scans, 934 convert. 5 empty reconstructions (all-zero-byte pdata) surfaced the `visu_pars`-is-list crash (fixed in #40). |

> **Searched but not raw ParaVision (excluded):** several large "Bruker + MRI"
> Zenodo hits ship **derived** NIfTI/MINC, not raw studies — e.g. the forepaw
> 14.1T electrostimulation dataset ([14793797](https://zenodo.org/records/14793797):
> BIDS `*_bold`/`*_dwi` NIfTI with `.bval`/`.bvec`, no `2dseq`), Alvino/Gini
> rs-fMRI mouse ([14534419](https://zenodo.org/records/14534419) /
> [14534751](https://zenodo.org/records/14534751), 80 GB), and the
> Mouse-Imaging-Centre `.mnc` records. The `MRSI-semiLASER`
> ([18461488](https://zenodo.org/records/18461488)) data is spectroscopic
> (non-image). The BrukerAPI records
> ([4048286](https://zenodo.org/records/4048286) /
> [4048253](https://zenodo.org/records/4048253) /
> [4522220](https://zenodo.org/records/4522220)) are already the CI fixtures listed above.

## Candidate datasets (found in the PCI-Community forum; not yet used)

From [pci-community.com](https://pci-community.com/) (Bruker Preclinical Imaging
Community; membership/login required). Bruker sample data and community
reconstruction repos that could extend coverage — none verified against
pvraw yet.

| Dataset | ParaVision | Source | Access / license | Notes |
|---|---|---|---|---|
| `SEQ_BRUKER_a_MP2RAGE_CS_360` | PV360 | [github.com/CRMSB/SEQ_BRUKER_a_MP2RAGE_CS_360](https://github.com/CRMSB/SEQ_BRUKER_a_MP2RAGE_CS_360) | public (see repo) | MP2RAGE compressed-sensing sequence + Julia recon and example Bruker images (BIDS export). Verify it ships raw data. |
| `SEQ_BRUKER_A_MP2RAGE_CS_PUBLIC` | PV6.0.1 | [github.com/aTrotier/SEQ_BRUKER_A_MP2RAGE_CS_PUBLIC](https://github.com/aTrotier/SEQ_BRUKER_A_MP2RAGE_CS_PUBLIC) | public (see repo) | MP2RAGE CS reconstruction + `pdata/$N` example. |
| `acidoCEST_MRI_Matlab` | — | [github.com/CAMEL-MartyPagel/acidoCEST_MRI_Matlab](https://github.com/CAMEL-MartyPagel/acidoCEST_MRI_Matlab) | public (see repo) | AcidoCEST analysis code "includes example data". |
| `Bruker_EPI_Reco` | — | [github.com/maximeYon/Bruker_EPI_Reco](https://github.com/maximeYon/Bruker_EPI_Reco) | public (see repo) | Bruker EPI reconstruction (double-sampling); may include sample raw data. |
| DWwave diffusion | PV6.0.1 | [osf.io/t9vqn](https://osf.io/t9vqn) | public (see project) | Arbitrary-waveform diffusion (EPI / spin-echo) sequence project. |
