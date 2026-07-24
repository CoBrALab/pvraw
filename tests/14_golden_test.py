"""Seam 1: the NIfTI a conversion produces, pinned to exact pre-recorded values.

``tests/goldens/images.json`` was captured before Bruker file reading was
delegated to `brukerapi` (ADR 0002), from the same public studies the fixtures
fetch. Every converted image is compared field by field: the affine at full
float64 precision, a sha256 of the stored data array, the shape and word type,
and the NIfTI header fields the conversion sets.

This is the only guard against the migration's worst failure mode, a quietly
mis-oriented image: ``08_orientation_test`` tests rotation mathematics in
isolation and cannot see an axis-order regression on real data.

Regenerate with ``tools/sweep_nifti.py`` only when a change to the output is
intended -- a difference here is a behaviour change to explain, not noise.
"""
import importlib.util
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from brkraw_legacy import BrukerLoader


def _load_sweep_tool():
    """``tools/sweep_nifti.py``, which defines what a golden holds.

    Imported rather than copied so the recorder and the comparison cannot drift:
    a field added to HEADER_FIELDS is compared here without a second edit.
    """
    path = Path(__file__).resolve().parents[1] / 'tools' / 'sweep_nifti.py'
    spec = importlib.util.spec_from_file_location('brkraw_sweep_nifti', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SWEEP = _load_sweep_tool()
GOLDENS = json.loads((Path(__file__).parent / 'goldens' / 'images.json').read_text())


def _same(actual, expected):
    """Equal, treating NaN as equal to NaN -- NaN marks an unset header field."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and \
            all(_same(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and \
            all(_same(a, b) for a, b in zip(actual, expected))
    return actual == expected or repr(actual) == repr(expected)


def _check(root, fixture):
    loader = BrukerLoader(str(root))
    checked = 0
    for scan_id, recos in sorted(GOLDENS[fixture].items()):
        for reco_id, expected in sorted(recos.items()):
            niis = loader.get_niftiobj(int(scan_id), int(reco_id))
            niis = niis if isinstance(niis, list) else [niis]
            assert len(niis) == expected['n_images'], \
                f'{fixture} {scan_id}/{reco_id}: image count changed'
            for index, want in expected['images'].items():
                got = SWEEP.golden(niis[int(index)])
                for field in ('shape', 'dtype', 'sha256', 'affine', 'header'):
                    assert _same(got[field], want[field]), \
                        f'{fixture} {scan_id}/{reco_id} image {index}: {field} changed'
                checked += 1
    assert checked, f'no goldens checked for {fixture}'


def test_pv51_conversion_matches_goldens(h2_study):
    _check(h2_study, 'h2_study')


def test_pv601_conversion_matches_goldens(lego_study):
    _check(lego_study, 'lego_study')


def test_pv7_conversion_matches_goldens(pv7_study):
    _check(pv7_study, 'pv7_study')


def test_pv360_conversion_matches_goldens(pv360_root):
    scan = pv360_root / 'T1_FLASH'
    if not (scan / 'acqp').exists():
        pytest.skip('PV360 T1_FLASH scan not available')
    _check(scan, 'pv360_scan')


def test_archive_converts_identically_to_a_directory(lego_study, tmp_path):
    """A study read out of a .zip gives the same image as the same study on disk.

    Archives are read in place through the pathlib protocol rather than
    extracted, so this pins that the two paths agree -- image for image, voxel
    for voxel.
    """
    archive = tmp_path / 'study.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED) as zf:
        for path in sorted(Path(lego_study).rglob('*')):
            if path.is_file():
                zf.write(path, str(Path(lego_study).name / path.relative_to(lego_study)))

    from_dir = BrukerLoader(str(lego_study))
    from_zip = BrukerLoader(str(archive))
    assert from_zip.avail_reco_id == from_dir.avail_reco_id

    compared = 0
    for scan_id, recos in sorted(GOLDENS['lego_study'].items()):
        for reco_id in sorted(recos):
            a = from_dir.get_niftiobj(int(scan_id), int(reco_id))
            b = from_zip.get_niftiobj(int(scan_id), int(reco_id))
            a = a if isinstance(a, list) else [a]
            b = b if isinstance(b, list) else [b]
            assert len(a) == len(b)
            for x, y in zip(a, b):
                assert np.array_equal(np.asarray(x.dataobj), np.asarray(y.dataobj))
                assert np.array_equal(x.affine, y.affine)
            compared += 1
    assert compared, 'no reconstructions compared'
