"""Archive inputs convert identically to their extracted contents (issue #62).

An archive and the directory it extracts to are the same PvDataset, so which
form the user hands over must not change what converts or what comes out.
That equivalence is the property that makes archive support trustworthy
rather than merely present, so it is asserted explicitly here -- affine, voxel
hash, full NIfTI header and BIDS sidecar -- over a whole study and over a
partial export (numbered scan directories with no ``subject`` file), which is
the case the directory branch of ``_open_container`` used to reject while the
archive branch accepted it.
"""
import hashlib
import shutil
import warnings
import zipfile
from pathlib import Path

import numpy as np
import pytest

from pvraw import BrukerLoader


def _zip_tree(src: Path, dest: Path) -> Path:
    """Archive `src` under its own name as the single top-level directory,
    the layout of a ParaVision ``.zip``/``.PvDatasets`` export."""
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_STORED) as zf:
        for member in sorted(src.rglob('*')):
            zf.write(member, Path(src.name) / member.relative_to(src))
    return dest


def _convert_everything(loader):
    """Every reconstruction's exact output, keyed by (scan_id, reco_id).

    A reconstruction that does not convert records its error instead, so a
    clean rejection (spectroscopy) must also be the same on both forms.
    """
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for sid, recos in loader.avail_reco_id.items():
            for rid in recos:
                try:
                    objs = loader.get_niftiobj(sid, rid)
                    objs = objs if isinstance(objs, list) else [objs]
                    out[(sid, rid)] = [
                        (obj.shape,
                         hashlib.sha256(np.asarray(obj.dataobj).tobytes()).hexdigest(),
                         bytes(obj.header.binaryblock))
                        for obj in objs
                    ]
                except Exception as error:
                    out[(sid, rid)] = f'{type(error).__name__}: {error}'
    return out


def _sidecars(loader):
    """Every reconstruction's BIDS sidecar dict, JSON-normalised for equality.

    A reconstruction whose sidecar fails to build records its error instead
    (issue #80 tracks the failures themselves); a failure must at least be the
    same failure on both forms.
    """
    from pvraw.lib.loader import _as_json_value
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for sid, recos in loader.avail_reco_id.items():
            for rid in recos:
                try:
                    out[(sid, rid)] = _as_json_value(loader._parse_json(sid, rid))
                except Exception as error:
                    out[(sid, rid)] = f'{type(error).__name__}: {error}'
    return out


@pytest.fixture(scope='session')
def lego_archive(lego_study, tmp_path_factory):
    """The lego_phantom study re-archived, byte-for-byte the same contents."""
    return _zip_tree(lego_study,
                     tmp_path_factory.mktemp('archive') / f'{lego_study.name}.zip')


def test_archive_and_directory_discover_the_same_scans(lego_study, lego_archive):
    assert BrukerLoader(str(lego_archive)).avail_reco_id == \
        BrukerLoader(str(lego_study)).avail_reco_id


def test_archive_converts_identically_to_directory(lego_study, lego_archive):
    """Same affine, voxel hash and header for every reconstruction; the scans
    that reject (spectroscopy) reject identically."""
    from_dir = _convert_everything(BrukerLoader(str(lego_study)))
    from_zip = _convert_everything(BrukerLoader(str(lego_archive)))
    assert from_zip == from_dir
    assert any(not isinstance(v, str) for v in from_dir.values())  # non-empty


def test_archive_bids_sidecars_match_directory(lego_study, lego_archive):
    assert _sidecars(BrukerLoader(str(lego_archive))) == \
        _sidecars(BrukerLoader(str(lego_study)))


def test_partial_export_converts_the_same_extracted_or_archived(lego_study, tmp_path_factory):
    """A partial export -- numbered scan directories, no ``subject`` file --
    yields its scans in either form. Regression: the directory form used to
    yield nothing while the archive form converted (issue #62)."""
    scan_ids = sorted(int(p.name) for p in lego_study.iterdir()
                      if p.is_dir() and p.name.isdigit())[:2]
    assert scan_ids, 'fixture study has no numbered scans'

    partial = tmp_path_factory.mktemp('partial') / 'partial_export'
    for sid in scan_ids:
        shutil.copytree(lego_study / str(sid), partial / str(sid))
    # The extension ParaVision uses for its own exports must work as well.
    archive = _zip_tree(partial, partial.parent / 'partial_export.PvDatasets')

    from_dir = _convert_everything(BrukerLoader(str(partial)))
    from_zip = _convert_everything(BrukerLoader(str(archive)))
    assert from_dir, 'partial export yielded no scans from the directory form'
    assert from_zip == from_dir
