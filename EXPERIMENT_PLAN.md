---
title: Does RECO_transposition belong to the data or to the reader?
tags: [orientation, brukerapi, decision]
---

# Does `RECO_transposition` belong to the data or to the reader?

`brukerapi` 0.4 started applying `RECO_transposition` / `VisuCoreTransposition`
to `dataset.data`. brkraw-legacy never did. Both cannot be right, and the
difference is a transposed image — the failure mode that stays invisible until
someone registers two datasets and they don't line up.

**Answered, on data already in `resources/testdata`. The reconstruction has
already applied the transposition; a reader must not apply it again.
brkraw-legacy's behaviour is correct and `brukerapi` 0.4 is a regression.**

The method is written up below so it can be re-run and challenged.

## The question, precisely

A 2dseq frame is stored as a 2-D array, and `RECO_transposition[frame]` is
non-zero for some frames. Two mutually exclusive readings:

**H<sub>applied</sub>** — the reconstruction transposed the frame before writing
it; the parameter *records what was done*. A reader that transposes again
produces a transposed image.

**H<sub>pending</sub>** — the frame is stored in acquisition (read, phase) order
and the parameter *instructs the reader*. Then brkraw-legacy has been writing
transposed images for years, and must also swap the first two columns of the
affine to match.

Note that applying the transposition *without* touching the affine — exactly
what `brukerapi` 0.4 does today — is the one combination that is wrong under
**both** hypotheses.

## Why it couldn't be deferred

Measured over `resources/testdata` (1,561 reconstructions holding a 2dseq):

| | count | share |
|---|---:|---:|
| transposition flag set | **1,142** | 73.2% |
| …of those, non-square in-plane (shape visibly changes) | 40 | 3.5% |
| …of those, mixed per-frame within one reconstruction | 97 | 8.5% |
| …of those, 3D acquisitions | 60 | 5.3% |
| spread | PV5.1, 6.0.1, 7.0.0, PV360 | all |

The common case, not an edge case — and `brukerapi>=0.4`, the floor ADR 0002
sets, pulls it in silently.

## The experiment

`new-orientation/` is a purpose-built orientation phantom study with a
documented acquisition table (`plantest_scaninfo_...tsv`). It contains **pairs
that differ only in readout direction** — the single variable that flips this
flag:

| study | pair | scans | transposition |
|---|---|---|---|
| `20201230_101610_CIC_LRMousePhantom_1_1` (PV6.0.1) | coronal 2D | 8 / 12 | set / clear |
| | axial 3D | 13 / 19 | clear / set |
| `20201230_CIC_PLANTEST_PV5_001.5S1` (PV5.1) | axial 3D | 8 / 19 | clear / set |

Same phantom, same session, same slice orientation, same voxel size — and
brkraw-legacy derives an **identical affine** for both members of a pair. Two
images of the same object, in the same plane, with the same affine, must
therefore hold the same array. That is ground truth internal to the data: no
external converter, no DICOM, no new acquisition.

So the test is a direct comparison. Correlate the pair as-is, and with one
member's in-plane axes swapped; whichever is higher is the layout in which the
two acquisitions agree.

## Result

Each pair, converted twice — once with a `brukerapi` that leaves the flag alone,
once with 0.4 which applies it:

| pair | | as-is | one transposed |
|---|---|---:|---:|
| PV6.0.1 coronal 2D, 8 vs 12 | flag ignored | **+0.951** | +0.283 |
| | flag applied (0.4) | +0.283 | **+0.951** |
| PV6.0.1 axial 3D, 13 vs 19 | flag ignored | **+0.992** | +0.532 |
| | flag applied (0.4) | +0.532 | **+0.992** |
| PV5.1 axial 3D, 8 vs 19 | flag ignored | **+0.928** | +0.426 |
| | flag applied (0.4) | +0.426 | **+0.928** |

Read it in one line: **when the flag is ignored the pair already agrees; when
0.4 applies it, the pair stops agreeing and only agrees again if you undo the
transposition.** Applying the flag *introduces* the disagreement between two
acquisitions of the same object.

H<sub>applied</sub> is confirmed and H<sub>pending</sub> is falsified, on two
ParaVision generations, in 2D and 3D, with the prediction inverting exactly as
the hypothesis requires.

This is consistent with Bruker's own documentation of
`ATB_SetRecoTranspositionFromLoops`
(`resources/manuals/PV5.1/pvman/D/Html/D08_MethodProg/`): the method program
"calculates the values of the `RECO_transposition` array depending on the image
orientation", i.e. the sequence tells the *reconstruction* what to do, and the
reconstruction does it.

## What follows

1. **brkraw-legacy needs no change.** Its output was right; the goldens in
   `tests/goldens/images.json` stand.
2. **Do not float to `brukerapi>=0.4`** until this is resolved upstream. It
   silently transposes 73% of reconstructions. ADR 0002's floor needs an upper
   bound, or the release needs to be waited for.
3. **Report it upstream** — with this experiment, which is reproducible from the
   public `new-orientation` data. Two separate defects:
   - applying a transposition the reconstruction already applied;
   - leaving `dataset.data.shape` disagreeing with `dataset.shape_final` when it
     does (`mch_dev_022/2/pdata/1`: declared `(178, 200, 100, 1)`, actual
     `(200, 178, 100, 1)`), silently, though the code carries a warning for
     exactly that case.
4. **Keep this document.** The next person to meet a transposed image will ask
   the same question.

## Residual uncertainty, and what would remove it

The result is strong but not exhaustive:

- Two ParaVision generations tested (5.1, 6.0.1). **Not** 7.0.0 or PV360 — and
  the flag's *source* differs by version (`RECO_transposition` for 1,052 of the
  corpus's reconstructions, `VisuCoreTransposition` for 90). Those need not
  behave alike.
- All three pairs are axis-aligned. An oblique acquisition, where the direction
  cosines are not a signed permutation, is untested.
- The correlation compares whole volumes. It would not notice a *further*
  symmetry-preserving error common to both members of a pair.

Two cheap ways to close those gaps without acquiring anything:

- **Sibling DICOM** — 25 reconstructions in the corpus have the flag set *and* a
  ParaVision DICOM export in `pdata/*/dicom/`. One is non-square, where the
  answer is visible in the array shape alone:
  `new-orientation/…LRMousePhantom…/25/pdata/1`, `VisuCoreSize [90, 108]`,
  110 DICOM files. If the DICOM frame is 90×108 the 2dseq is stored
  untransposed. Needs `pydicom`, not currently installed.
- **Independent converter** — `bruker2nifti_qa/raw/McGill_Orientation/` ships
  reference `.nii` files beside the raw data (e.g.
  `bb20130412_APM_DEV_Orient.jl1/3/3.nii`, 4 MB, real) from a project whose
  purpose is orientation QA.

If you do acquire, the specification that would settle every future orientation
question at once:

1. An **asymmetric phantom** — distinguishable left/right *and* head/foot *and*
   up/down; a structured phantom with a unique corner marker beats a mouse
   phantom.
2. **Readout-direction pairs** as above: identical geometry, toggle
   `PVM_SPackArrReadOrient` only. Both 2D multi-slice and 3D.
3. A **non-square in-plane matrix** (e.g. 96×128) — squareness is why 96% of the
   existing corpus cannot answer this from the shape alone.
4. An **oblique variant**, rotated about one axis and about all three.
5. **DICOM export enabled** for the same reconstructions.
6. Repeated on **each ParaVision generation you support**.

Roughly 16 short acquisitions, one phantom, one session.

## Re-running it

```bash
# with the currently installed brukerapi
uv run --no-sync python - <<'PY'
import warnings, numpy as np
warnings.simplefilter('ignore')
from brkraw_legacy import BrukerLoader

STUDIES = {
    'resources/testdata/new-orientation/20201230_101610_CIC_LRMousePhantom_1_1':
        [('coronal 2D', 8, 12), ('axial 3D', 13, 19)],
    'resources/testdata/new-orientation/20201230_CIC_PLANTEST_PV5_001.5S1':
        [('axial 3D', 8, 19)],
}
for study, pairs in STUDIES.items():
    d = BrukerLoader(study)
    def arr(s):
        n = d.get_niftiobj(s, 1)
        n = n[0] if isinstance(n, list) else n
        a = np.asarray(n.dataobj, dtype=float)
        return (a - a.mean()) / (a.std() or 1)
    for name, x, y in pairs:
        a, b = arr(x), arr(y)
        r, rt = float((a*b).mean()), float((a*np.swapaxes(b,0,1)).mean())
        print(f'{name:12} {x:>3} vs {y:<3} as-is {r:+.3f}  transposed {rt:+.3f}')
PY
```

A pair that agrees **as-is** means the flag must be left alone.
