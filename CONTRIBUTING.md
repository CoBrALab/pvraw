# Contributing to pvraw

Thank you for your interest in contributing. Bug fixes, new features and documentation
improvements are all welcome.

## Reporting issues

Use the [Issues](https://github.com/gdevenyi/pvraw/issues) section of this repository. For a bug,
the things that actually help are: your ParaVision version, the `pvraw` version, the scan and
reco ids involved, and the output of `pvraw info` on the study.

A problem in parsing a parameter file, assembling an array, or in the voxel-to-patient
affine belongs upstream in [`brukerapi`](https://github.com/isi-nmr/brukerapi-python),
which does all Bruker file reading for pvraw
([ADR 0002](docs/adr/0002-delegate-bruker-reading-to-brukerapi.md)); this project owns
how the subject was framed, the NIfTI headers, and BIDS.

If your contribution targets upstream [BrkRaw](https://github.com/BrkRaw/brkraw)'s 0.5+
architecture, direct it there instead — pvraw is developed independently and does not merge
upstream changes.

## Pull requests

- **Code changes** — document them, particularly anything driven by a ParaVision compatibility
  problem.
- **New features** — include tests in `tests/`, following the existing numbered-by-layer naming.

Before opening a pull request, run:

```bash
uv run ruff check .            # must be clean
uv run pytest -m "not data"    # offline suite
```

Anything that could move geometry or change sidecars also needs a
`tools/sweep_nifti.py --compare` run against a corpus. Geometry is verified against
data, not against recorded output. The README's Development section is the reference
for the full test suite, the sample-data cache and the sweep tools.

## Before you start

Check the open issues to see whether your question has already been answered or the feature
already discussed. If you are unsure about a change, open an issue first.
