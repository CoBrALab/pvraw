"""app.tonifti (StudyToNifti) NIfTI-assembly tests against public sample data."""
import numpy as np
import pytest

from pvraw import BrukerLoader
from pvraw.app.tonifti import StudyToNifti
from pvraw.lib.errors import UnexpectedError


def test_api_matches_loader_across_scans(lego_study):
    """BrukerLoader.get_niftiobj and StudyToNifti.get_nifti1image are one path.

    The loader delegates image assembly to app.tonifti, so the two must produce
    byte-identical output -- same image count, ndim, affine and data -- for every
    scan. This pins that delegation (and the shared assembly) against regression;
    a quorum guards against a vacuous pass.
    """
    loader = BrukerLoader(str(lego_study))
    api = StudyToNifti(str(lego_study))

    compared = 0
    for sid in loader.avail_scan_id:
        for rid in loader.avail_reco_id.get(sid, [1]):
            try:
                lo = loader.get_niftiobj(sid, rid)
                ap = api.get_nifti1image(sid, rid)
            except Exception:
                continue
            lo = lo if isinstance(lo, list) else [lo]
            ap = ap if isinstance(ap, list) else [ap]
            assert len(lo) == len(ap), f'scan {sid},{rid}: {len(lo)} vs {len(ap)} images'
            for a, b in zip(lo, ap):
                assert a.ndim == b.ndim
                assert np.allclose(a.affine, b.affine, atol=1e-4)
                assert np.array_equal(np.asarray(a.dataobj), np.asarray(b.dataobj))
            compared += 1

    assert compared >= 10, f'expected to compare many scans, only did {compared}'


def test_spectroscopic_scan_rejected_cleanly(h2_study):
    """Non-image (spectroscopic) scans must raise a clear, catchable error.

    VisuCoreDimDesc is not all-'spatial' for spectroscopy (PRESS/STEAM/...), so
    the data can't become a NIfTI. The API must reject it with an UnexpectedError
    naming 'non-image data' -- matching the BrukerLoader -- rather than crashing
    with an opaque KeyError/TypeError from deep in the image pipeline.
    """
    loader = BrukerLoader(str(h2_study))
    target = None
    for sid, recos in loader.avail_reco_id.items():
        vp = loader._get_visu_pars(sid, recos[0])
        if loader._get_dim_info(vp)[1] != 'spatial_only':
            target = (sid, recos[0])
            break
    if target is None:
        pytest.skip('no spectroscopic scan in sample')
    with pytest.raises(UnexpectedError, match='non-image'):
        StudyToNifti(str(h2_study)).get_nifti1image(*target)
