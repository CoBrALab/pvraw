"""Unit tests for app.tonifti.header.Header (NIfTI header population).

Pure-unit: the Header class only needs a ScanInfo-shaped object and a
Nifti1Image, so these run offline (no ``data`` marker) with a light stub.
"""
from types import SimpleNamespace

import nibabel as nib
import numpy as np
import pytest

from brkraw_legacy.app.tonifti.header import Header


def _scaninfo(slice_order_scheme='Sequential', num_cycles=1, time_step=0.0,
              scan_time=0.0, num_slices=10, slope=1.0, offset=0.0):
    """A minimal ScanInfo stub carrying only what Header reads."""
    return SimpleNamespace(
        slicepack={'slice_order_scheme': slice_order_scheme,
                   'num_slices_each_pack': [num_slices]},
        cycle={'num_cycles': num_cycles, 'time_step': time_step,
               'scan_time': scan_time},
        dataarray={'slope': slope, 'offset': offset},
    )


def _make_header(info, shape=(8, 8, 10), affine=None, scale_mode='header', data=None):
    affine = np.diag([0.3, 0.3, 0.7, 1.0]) if affine is None else affine
    arr = np.zeros(shape, dtype='int16') if data is None else data
    nii = nib.Nifti1Image(arr, affine)
    return Header(scaninfo=info, nifti1image=nii, scale_mode=scale_mode).get()


@pytest.mark.parametrize('scheme, expected', [
    ('Sequential', 1),
    ('Reverse_sequential', 2),
    ('Interlaced', 3),
    ('Reverse_interlaced', 4),
])
def test_slice_code_maps_bruker_scheme(scheme, expected):
    """Each known PVM_ObjOrderScheme maps to its NIfTI slice_code (H1 regression).

    The old code's ``... or slice_order_scheme`` short-circuit forced slice_code
    to 0 for every non-empty scheme, so these mappings were dead code.
    """
    out = _make_header(_scaninfo(slice_order_scheme=scheme))
    assert int(out.header['slice_code']) == expected


def test_slice_code_unknown_scheme_is_zero_and_warns():
    info = _scaninfo(slice_order_scheme='User_defined_slice_scheme')
    with pytest.warns(UserWarning, match="slice_code"):
        out = _make_header(info)
    assert int(out.header['slice_code']) == 0


def test_spatial_units_labelled_mm_without_cycles():
    """Non-cine scans must still label spatial units as mm (H4 regression).

    Previously set_xyzt_units ran only in the cycle branch, so ordinary
    anatomical scans were written with NIFTI_UNITS_UNKNOWN.
    """
    out = _make_header(_scaninfo(num_cycles=1))
    assert out.header.get_xyzt_units()[0] == 'mm'


def test_time_step_on_4d_is_scantime_per_volume():
    """A 4D series carries mm + sec and a per-volume time step on pixdim[4], taken
    from ScanTime/num_volumes -- the wall-clock time between volumes, i.e. the BIDS
    func RepetitionTime (which exceeds the sequence TR for multi-shot/averaged EPI).
    """
    # 8000 ms scan / 4 volumes -> 2 s per volume
    out = _make_header(_scaninfo(scan_time=8000.0, num_slices=10), shape=(8, 8, 10, 4))
    assert out.header.get_xyzt_units() == ('mm', 'sec')
    assert float(out.header['pixdim'][4]) == pytest.approx(2.0)
    assert float(out.header['slice_duration']) == pytest.approx(2.0 / 10)


def test_3d_series_has_no_time_step():
    """A 3D scan is mm-only with no time step, even when a scan time exists."""
    out = _make_header(_scaninfo(scan_time=8000.0), shape=(8, 8, 10))
    assert out.header.get_xyzt_units()[1] == 'unknown'
    assert float(out.header['pixdim'][4]) == pytest.approx(1.0)      # nibabel default


def test_4d_without_scan_time_sets_sec_units_without_crashing():
    """A missing/zero ScanTime must not crash: sec units are still set for the 4D
    series, but pixdim[4] is left at the default (no value to divide)."""
    out = _make_header(_scaninfo(scan_time=0.0), shape=(8, 8, 10, 3))
    assert out.header.get_xyzt_units() == ('mm', 'sec')
    assert float(out.header['pixdim'][4]) == pytest.approx(1.0)      # left default


def test_sform_and_qform_both_scanner_anat(tmp_path):
    """Both qform and sform are set with the scanner-anat code (M1 regression).

    A from-affine Nifti1Image defaults to sform_code=2 and an unset qform
    (code 0). These must round-trip through a save as code 1 for both forms,
    carrying the same affine.
    """
    affine = np.diag([0.25, 0.25, 0.6, 1.0])
    affine[:3, 3] = [-12.0, -9.0, -5.0]
    out = _make_header(_scaninfo(), affine=affine)

    p = tmp_path / 'x.nii'
    out.to_filename(str(p))
    h = nib.load(str(p)).header
    assert int(h['qform_code']) == 1        # NIFTI_XFORM_SCANNER_ANAT
    assert int(h['sform_code']) == 1
    assert np.allclose(h.get_sform(), affine, atol=1e-4)
    assert np.allclose(h.get_qform(), affine, atol=1e-4)


def test_slice_extent_records_axis_and_range():
    """slice_start/end and the slice axis of dim_info are set (L1 regression).

    Without these, a non-zero slice_code cannot be applied by slice-timing tools.
    The slice axis is always third; freq/phase are left unset here.
    """
    out = _make_header(_scaninfo(), shape=(8, 8, 10))
    assert out.header.get_dim_info() == (None, None, 2)
    assert int(out.header['slice_start']) == 0
    assert int(out.header['slice_end']) == 9        # shape[2] - 1


def test_cal_range_in_true_units_and_descrip():
    """cal_min/cal_max are the data range in true units; descrip is set (L2).

    With scl_slope=2/scl_inter=5 in the header the stored range [10, 200] maps to
    a true display range [25, 405].
    """
    arr = np.full((8, 8, 10), 10, dtype='int16')
    arr.flat[0] = 200
    out = _make_header(_scaninfo(slope=2.0, offset=5.0), data=arr, scale_mode='header')
    assert float(out.header['cal_min']) == pytest.approx(25.0)     # 2*10 + 5
    assert float(out.header['cal_max']) == pytest.approx(405.0)    # 2*200 + 5
    assert bytes(out.header['descrip']).rstrip(b'\x00') == b'brkraw-legacy'
