# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Released versions are on [PyPI](https://pypi.org/project/pvraw/) and on the
[releases page](https://github.com/CoBrALab/pvraw/releases).

## 1.2.0 — 2026-08-24

### Changed

- The install instructions name PyPI first: `uv tool install pvraw` for the command-line
  tool and `uv add pvraw` for the Python API. The `git+https` form is kept for running a
  change that is not released yet, and the source checkout is the development install.
- The first-conversion tutorial installs from PyPI as well.

### Added

- This changelog.
- A GitHub release, carrying the changelog section for the version and the built sdist
  and wheel, is now created by CI for every version tag.

## 1.1.0 — 2026-08-24

First release published to PyPI.

### Added

- `pvraw info` gained a structured core (`BrukerLoader.info_dict()`) and a machine-parsable
  `--json` output (#88).

### Changed

- The subject/study identity vocabulary is named per attribute (#96) and read through
  `brukerapi`'s `Dataset` properties (#98).
- `reshipe` is replaced by a native recipe resolver (#91).
- The BIDS session is read from the study directory name (#93).
- The affine rotates from the declared subject position to the actual one (#97).
- The `brukerapi` floor is raised to 0.4.6.

## 1.0.0

The first release under the `pvraw` name. Committed but never tagged or published, so
1.1.0 is what a user can install; the entry is kept because the version string is in
released files.

The version history before it was fiction: the only tags this repo ever carried were
upstream BrkRaw's 0.3.0–0.3.4b0 from 2020. Nothing was released as 0.4.0, 0.5.0 or 0.6.0
— those were version strings in files with no release behind them. Earlier work was
installable from git only, under the name `brkraw-legacy`, and signed its output that
way; see the naming note in the README if you hold a dataset converted before 1.0.0.
