"""Regression tests for raw->NIfTI conversion against public sample datasets.

These exercise paths that previously crashed or produced wrong output, using
the public BrukerAPI test datasets (Zenodo) and the PV360 standard-data repo;
each skips when its dataset or a real (non-LFS-stub) ``2dseq`` is unavailable.
"""
import gc
import warnings

import pytest

from brkraw_legacy import BrukerLoader


def _has_real_2dseq(loader, scan_id, reco_id, min_bytes=1024):
    """Skip helper: LFS-backed fixtures may ship pointer-stub 2dseq files."""
    try:
        path = loader.study.get_scan(scan_id).get_dataset(reco_id).path
        return path.stat().st_size >= min_bytes
    except Exception:                          # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Frame-group parsing no longer crashes on single/complex-comment groups
# --------------------------------------------------------------------------- #

def test_frame_group_info_parses_all_scans(h2_study):
    """Every reconstruction reports its Frame Groups as (name, size) pairs."""
    d = BrukerLoader(str(h2_study))
    for sid, recos in d.avail_reco_id.items():
        for rid in recos:
            groups = d.get_frame_groups(sid, rid)   # must not raise
            assert all(isinstance(name, str) and int(size) > 0
                       for name, size in groups)


def test_all_reconstructions_convert_through_app_tonifti(h2_study):
    """Every reconstruction of 0.2H2 must either convert or be cleanly rejected as
    non-image data through the app.tonifti path (``get_niftiobj``), matching the
    loader-native path. Regression guard for derived ISA/DTI parametric maps
    (scans 31/32/33 recos >=2) that used to crash only on the app.tonifti path."""
    d = BrukerLoader(str(h2_study))
    failures = []
    for sid, recos in d.avail_reco_id.items():
        for rid in recos:
            try:
                d.get_niftiobj(sid, rid)
            except Exception as e:                  # noqa: BLE001
                if 'non-image data' not in str(e):
                    failures.append((sid, rid, '{}: {}'.format(type(e).__name__, e)))
    assert not failures, 'unexpected conversion failures: {}'.format(failures)


# --------------------------------------------------------------------------- #
# Multi-slice-package with heterogeneous pack sizes (e.g. 5/3/5 slices)
# --------------------------------------------------------------------------- #

def test_multi_slicepack_heterogeneous(lego_study):
    """lego_phantom scan 8 is a 13-frame scout genuinely packed [5, 3, 5]."""
    d = BrukerLoader(str(lego_study))
    sid, rid = 8, 1
    if not _has_real_2dseq(d, sid, rid):
        pytest.skip('scan 8 2dseq is a stub')
    counts = d._get_slice_info(sid, rid)['num_slices_each_pack']
    assert counts == [5, 3, 5]
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        objs = d.get_niftiobj(sid, rid)
    assert [o.shape[2] for o in objs] == [5, 3, 5]
    # slices must total the frame count with no loss/overlap
    assert sum(o.shape[2] for o in objs) == 13


# --------------------------------------------------------------------------- #
# Spectroscopic / non-image data is rejected cleanly, not with a cryptic crash
# --------------------------------------------------------------------------- #

def test_spectroscopic_rejected_cleanly(h2_study):
    d = BrukerLoader(str(h2_study))
    # find a spectroscopic scan (VisuCoreDimDesc not purely spatial)
    target = None
    for sid, recos in d.avail_reco_id.items():
        vp = d._get_visu_pars(sid, recos[0])
        if d._get_dim_info(vp)[1] != 'spatial_only':
            target = (sid, recos[0])
            break
    if target is None:
        pytest.skip('no spectroscopic scan in sample')
    with pytest.raises(Exception, match='non-image data'):
        d.get_niftiobj(*target)


def test_empty_reconstruction_rejected_cleanly(tmp_path):
    """A reconstruction whose pdata files are all zero bytes carries no image
    data. It must be rejected by name, not crash deep in the image pipeline."""
    from brukerapi.dataset import Dataset
    from brukerapi.exceptions import InvalidDataset

    proc = tmp_path / '1' / 'pdata' / '1'
    proc.mkdir(parents=True)
    (proc / 'visu_pars').write_bytes(b'')
    (proc / '2dseq').write_bytes(b'')
    with pytest.raises(InvalidDataset, match='empty'):
        Dataset(proc / '2dseq')


def test_stub_2dseq_rejected_cleanly(tmp_path):
    """A stub 2dseq (an unpulled git-LFS pointer) holds a text pointer, not image
    data, and must be rejected with a message naming the cause."""
    from brukerapi.dataset import Dataset
    from brukerapi.exceptions import InvalidDataset

    proc = tmp_path / '1' / 'pdata' / '1'
    proc.mkdir(parents=True)
    (proc / 'visu_pars').write_text(MINIMAL_VISU_PARS)
    (proc / '2dseq').write_bytes(b'version https://git-lfs.github.com/spec/v1\n'
                                 b'oid sha256:deadbeef\n')
    with pytest.raises(InvalidDataset, match='(?i)git lfs'):
        Dataset(proc / '2dseq')


# --------------------------------------------------------------------------- #
# Loose-scan collection (no subject file) loads without a TypeError
# --------------------------------------------------------------------------- #

def test_non_pvdataset_directory_is_clean(pv360_root):
    loader = BrukerLoader(str(pv360_root))   # must not raise
    # the collection root has no scans of its own -> not a single PvDataset
    assert loader.is_pvdataset is False


# --------------------------------------------------------------------------- #
# Standalone scan/EXPNO directory (no subject file) loads as a one-scan dataset
# --------------------------------------------------------------------------- #

def test_standalone_scan_directory_loads(pv360_root):
    scan = pv360_root / 'T1_FLASH'
    if not (scan / 'acqp').exists():
        pytest.skip('PV360 T1_FLASH scan not available')
    if not _has_real_2dseq(BrukerLoader(str(scan)), 1, 1):
        pytest.skip('T1_FLASH 2dseq is an unpulled LFS stub')
    d = BrukerLoader(str(scan))
    assert d.is_pvdataset is True
    assert d.num_scans == 1
    assert d.avail_reco_id == {1: [1]}
    assert d.subj_id is None                  # no subject file
    nii = d.get_niftiobj(1, 1)
    nii = nii[0] if isinstance(nii, list) else nii
    assert nii.ndim == 3 and all(s > 0 for s in nii.shape)


# --------------------------------------------------------------------------- #
# Conversion must not leak the 2dseq/fid file handles (reader-owns-handle)
# --------------------------------------------------------------------------- #

def test_conversion_releases_file_handles(lego_study):
    """A raw->NIfTI conversion closes the 2dseq/fid handles it opens instead of
    leaving them for the garbage collector -- which emits ResourceWarnings and,
    off CPython, leaks descriptors. Recording warnings while converting a few
    scans catches a regression of the reader-owns-handle behaviour.
    """
    loader = BrukerLoader(str(lego_study))
    converted = 0
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        for sid in loader.avail_scan_id:
            for rid in loader.avail_reco_id.get(sid, [1]):
                try:
                    nii = loader.get_niftiobj(sid, rid)
                except Exception:
                    continue
                del nii
                converted += 1
                break                       # one reconstruction per scan is enough
            if converted >= 3:
                break
        gc.collect()                        # run finalizers inside the recording block
    if not converted:
        pytest.skip('no convertible scan in sample')
    unclosed = [str(w.message) for w in caught
                if issubclass(w.category, ResourceWarning)
                and 'unclosed file' in str(w.message)]
    assert not unclosed, 'leaked file handles during conversion: {}'.format(unclosed)


#: A minimal but valid 2dseq header, for the stub-rejection test above.
MINIMAL_VISU_PARS = """##TITLE=Parameter List, ParaVision 6.0.1
##JCAMPDX=4.24
##$VisuCreatorVersion=<6.0.1>
##$VisuCoreDim=2
##$VisuCoreSize=( 2 )
4 3
##$VisuCoreDimDesc=( 2 )
spatial spatial
##$VisuCoreExtent=( 2 )
20 15
##$VisuCoreFrameCount=1
##$VisuCoreWordType=_16BIT_SGN_INT
##$VisuCoreByteOrder=littleEndian
##$VisuCoreDataSlope=( 1 )
1
##$VisuCoreDataOffs=( 1 )
0
##$VisuCoreOrientation=( 1, 9 )
1 0 0 0 1 0 0 0 1
##$VisuCorePosition=( 1, 3 )
0 0 0
##END=
"""
