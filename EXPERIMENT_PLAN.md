---
title: Does RECO_transposition belong to the data or to the reader?
tags: [orientation, brukerapi, decision]
---

# Does `RECO_transposition` belong to the data or to the reader?

`brukerapi` 0.4 started applying `RECO_transposition` / `VisuCoreTransposition`
to `dataset.data`. pvraw never did. Both cannot be right, and the
difference is a transposed image — the failure mode that stays invisible until
someone registers two datasets and they don't line up.

**Answered, on data already in `resources/testdata`. The reconstruction has
already applied the transposition; a reader must not apply it again.
pvraw's behaviour is correct and `brukerapi` 0.4.0 was a regression.**

**Resolved upstream, and the geometry question with it.** pvraw no
longer derives an affine at all: `brukerapi` 0.4.2 supplies it, and the
disk-slice-order convention below is settled by taking its array and its affine
together (ADR 0002, amended). The reasoning is kept because the method is what
matters, and because it found a slice-spacing and a slice-packaging defect that
nothing else had.

**Transposition, resolved upstream.** Reported as isi-nmr/brukerapi-python#153 (with #154 for
the shape inconsistency it caused); `_apply_transposition` was removed in full
and released as **0.4.1**. 0.4.0 is on PyPI and carries the regression, which is
part of why pvraw floors above it (the floor is now 0.4.5; see
`pyproject.toml`). Against 0.4.1 every golden matched its pre-migration value again —
`tests/goldens/` has since been dropped, for the reason recorded in ADR 0002.

The method is written up below so it can be re-run and challenged — the question
will come back the next time someone meets a transposed image.

## The question, precisely

A 2dseq frame is stored as a 2-D array, and `RECO_transposition[frame]` is
non-zero for some frames. Two mutually exclusive readings:

**H<sub>applied</sub>** — the reconstruction transposed the frame before writing
it; the parameter *records what was done*. A reader that transposes again
produces a transposed image.

**H<sub>pending</sub>** — the frame is stored in acquisition (read, phase) order
and the parameter *instructs the reader*. Then pvraw has been writing
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
documented acquisition table (`plantest_scaninfo_...tsv`). Its provenance is not
recorded in `resources/testdata/README.md`, so treat it as local data of unknown
redistributability until that is established. It contains **pairs that differ
only in readout direction** — the single variable that flips this flag:

| study | pair | scans | transposition |
|---|---|---|---|
| `20201230_101610_CIC_LRMousePhantom_1_1` (PV6.0.1) | coronal 2D | 8 / 12 | set / clear |
| | axial 3D | 13 / 19 | clear / set |
| `20201230_CIC_PLANTEST_PV5_001.5S1` (PV5.1) | axial 3D | 8 / 19 | clear / set |

The sample is placed identically throughout the study and only console settings
are varied, so a pair differs in exactly one thing. Verified from the
parameters rather than the table's prose — for all three pairs:

| | 13 (read L_R) | 19 (read A_P) |
|---|---|---|
| `PVM_SPackArrSliceOrient` | axial | axial |
| `PVM_SPackArrGradOrient` (**acquisition** frame) | `[[1,0,0],[0,1,0],[0,0,1]]` | `[[0,1,0],[1,0,0],[0,0,1]]` |
| `VisuCoreOrientation` (**image** frame) | identity | identity |
| `VisuCorePosition`, `VisuCoreSize`, `VisuCoreExtent` | — | identical |
| transposition flag | clear | **set** |

Read the middle two rows together and the question is already answered. The
acquisition frames differ by exactly a read/phase transposition. The *image*
frames are identical. And the flag is set on precisely the one where the two
differ — which is what it means to record a transposition that has been applied
to bring the acquired frame into the image frame.

`VisuCoreOrientation` describes the stored 2dseq. It is the same for both, so
the two stored arrays must be in the same layout. If instead the flag were
pending on read, scan 19's array would still be in the acquisition frame while
its own `VisuCoreOrientation` claimed the image frame — the parameter would be
misdescribing the data it sits next to.

That is ground truth internal to the data: no external converter, no derived
product, no new acquisition. The measurement below confirms what the parameters
already say.

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

### A second, self-contained check

The phantom is not the only evidence, and the other kind needs no phantom at
all. Take any flagged non-square reconstruction —
`pv6/full/mch_dev_022/2/pdata/1`:

```
VisuCoreSize    [178, 200, 100]
VisuCoreExtent  [16.02, 18.00, 9.00]   ->  0.090, 0.090, 0.090 mm   isotropic
```

The field of view divides by the matrix, *in `VisuCoreSize` order*, into
isotropic voxels. Pair that same extent with a transposed array (200, 178, 100)
and the voxels come out 0.080 x 0.101 mm — anisotropic, and wrong. So
`VisuCoreExtent` describes the untransposed array, and so, by construction, do
`VisuCorePosition` and `VisuCoreOrientation`: the entire geometry block any
consumer uses to build an affine.

Transposing `data` alone therefore puts it at odds with every geometry parameter
in `visu_pars`, on any dataset — no phantom, no pairs, no registration.

This is consistent with Bruker's own documentation of
`ATB_SetRecoTranspositionFromLoops`
(`resources/manuals/PV5.1/pvman/D/Html/D08_MethodProg/`): the method program
"calculates the values of the `RECO_transposition` array depending on the image
orientation", i.e. the sequence tells the *reconstruction* what to do, and the
reconstruction does it.

## What follows

1. **pvraw needed no change.** Its output was right, and matched its
   pre-migration goldens again on 0.4.1.
2. **Floor above `brukerapi==0.4.0`**, which is on PyPI and silently transposes
   73% of reconstructions. The floor is now `>=0.4.2`, raised again for the
   affine.
3. **Reported and fixed upstream** — #153 (applying a transposition the
   reconstruction had already applied) and #154 (`dataset.data.shape`
   disagreeing with `dataset.shape_final` as a result, silently, though the code
   carried a warning for exactly that case). Both closed; `_apply_transposition`
   removed in 0.4.1.
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

**No derived product in the corpus counts as ground truth.** Not the `.nii`
files shipped beside the raw data, not the `pdata/*/dicom/` exports — their
provenance and correctness are unestablished, and one set is explicitly
disqualified: `resources/testdata/README.md` records the McGill orientation
studies as "collected improperly, so it is not a valid orientation reference".
An orientation answer must not be built on another converter's output.

That constraint is why the two experiments above were chosen as they were, and
it costs nothing here: neither touches a NIfTI or a DICOM. The pair experiment
reads 2dseq arrays only; the geometry check reads `visu_pars` only. **The
conclusion rests entirely on raw acquisition data and the parameters Bruker
wrote next to it.**

Closing the remaining gaps therefore means new acquisitions, not new references.

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
5. Repeated on **each ParaVision generation you support**.

Roughly 16 short acquisitions, one phantom, one session.

## Re-running it

```bash
# with the currently installed brukerapi
uv run --no-sync python - <<'PY'
import warnings, numpy as np
warnings.simplefilter('ignore')
from pvraw import BrukerLoader

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
