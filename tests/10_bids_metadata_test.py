"""Unit tests for the Bruker->BIDS metadata reference tables (lib/reference.py)
and the equation resolver (lib/utils.meta_check_express).

Pure-unit (offline): resolve individual reference entries with stub parameter
objects (``.parameters`` dicts) via meta_get_value, asserting on the emitted
value rather than only its BIDS well-formedness.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_legacy.lib.reference import COMMON_META_REF, FMRI_META_REF
from brkraw_legacy.lib.utils import func_volume_tr, meta_check_express, meta_get_value


class _p(dict):
    """A stub acqp/method/visu_pars: a JCAMPDX's read accessors over a dict."""
    def __init__(self, **params):
        super().__init__(params)

    def get_parameter(self, key):
        return SimpleNamespace(value=self[key], nested=[self[key]], val_str='')


def _resolve(field, acqp=None, method=None, visu=None):
    return meta_get_value(COMMON_META_REF[field], acqp or _p(), method or _p(), visu or _p())


# --- equation resolver (meta_check_express) --------------------------------

def test_equation_fields_resolve():
    """Equation-based fields must actually compute (PEP 667 regression).

    The old exec()-into-locals() resolver silently returned None for every
    equation field on Python 3.13+. Cover several equation shapes: array math,
    scalar math, str(), and len().
    """
    visu = _p(VisuAcqEchoTime=[10.0, 20.0],       # array math: np.array(TE)/1000
              VisuAcqImagingFrequency=400.0,       # scalar math: Freq/42.576
              VisuSystemOrderNumber=12345,         # str(SN)
              NSLICES=3)                           # multi-slice -> 'k'

    assert np.allclose(_resolve('EchoTime', visu=visu), [0.010, 0.020])
    assert _resolve('MagneticFieldStrength', visu=visu) == pytest.approx(400.0 / 42.576)
    assert _resolve('DeviceSerialNumber', visu=visu) == '12345'
    # SliceEncodingDirection: brkraw reconstructs slices on the k axis; emit 'k' for
    # multi-slice data (a BIDS string, not the integer the old mapping produced).
    assert _resolve('SliceEncodingDirection', visu=visu) == 'k'
    # single-slice -> omitted (not 'k')
    assert _resolve('SliceEncodingDirection', visu=_p(NSLICES=1)) is None


def test_equation_field_omitted_when_input_missing():
    """A missing referenced parameter yields None (field omitted), not 'None'."""
    # VisuAcqImagingFrequency absent -> MagneticFieldStrength cannot be computed.
    assert _resolve('MagneticFieldStrength', visu=_p()) is None
    # str(SN) with SN absent must omit rather than emit the literal 'None'.
    assert _resolve('DeviceSerialNumber', visu=_p()) is None


def test_unused_declared_variable_does_not_suppress_field():
    """A declared-but-unused missing variable must not omit the field.

    Guards the resolver against fields like TotalReadoutTime that declare an
    extra variable (ETL) not referenced by the equation: the field must still
    compute when that variable is absent.
    """
    val = {'X': 'PresentParam', 'Unused': 'MissingParam', 'Equation': 'X * 2'}
    acqp = _p(PresentParam=5)      # MissingParam absent -> Unused resolves to None
    assert meta_check_express(val, acqp, _p(), _p()) == 10


# --- SliceTiming (H2) -------------------------------------------------------

def test_slicetiming_spans_full_tr_and_matches_slice_count():
    """SliceTiming spans [0, TR) per volume and has one entry per slice (NSLICES).

    The length comes from NSLICES, never VisuCoreFrameCount (= NI*NR), so it does
    not shrink with the volume count. It is emitted only when the acquisition-order
    length matches NSLICES.
    """
    n_slices, tr_ms = 20, 2000.0
    acqp = _p(ACQ_obj_order=list(range(n_slices)), NSLICES=n_slices)
    visu = _p(VisuAcqRepetitionTime=tr_ms)
    st = np.asarray(_resolve('SliceTiming', acqp=acqp, visu=visu))

    assert st.shape == (n_slices,)
    assert st.min() == 0.0
    # sequential: last slice at (N-1)/N * TR, in seconds -- full span, not 1/NR of it
    assert np.isclose(st.max(), (tr_ms / 1000.0) * (n_slices - 1) / n_slices)


def test_slicetiming_follows_interleaved_order():
    """Interleaved acquisition produces distinct, TR-spanning slice times.

    ACQ_obj_order[slot] = the slice acquired at that slot; argsort inverts it to
    each slice's acquisition time.
    """
    acqp = _p(ACQ_obj_order=[0, 2, 1, 3], NSLICES=4)   # 4-slice interleaved (from PV data)
    visu = _p(VisuAcqRepetitionTime=1000.0)
    st = np.asarray(_resolve('SliceTiming', acqp=acqp, visu=visu))
    assert st.shape == (4,)
    assert np.allclose(st, [0.0, 0.5, 0.25, 0.75])     # slice s at slot inv[s] * TR/N
    assert len(set(np.round(st, 6))) == 4              # all four slice times distinct


def test_slicetiming_omitted_when_order_length_mismatches_slice_count():
    """Multi-echo/multi-TI orders have length NSLICES*N != NSLICES -> omit rather
    than emit a wrong-length (misleading) SliceTiming."""
    acqp = _p(ACQ_obj_order=list(range(9)), NSLICES=3)  # e.g. 3 slices * 3 echoes
    assert _resolve('SliceTiming', acqp=acqp, visu=_p(VisuAcqRepetitionTime=1000.0)) is None
    # single-slice -> omitted too (NSLICES == 1)
    acqp1 = _p(ACQ_obj_order=0, NSLICES=1)
    assert _resolve('SliceTiming', acqp=acqp1, visu=_p(VisuAcqRepetitionTime=1000.0)) is None


# --- readout timing (M3) ----------------------------------------------------

def test_effective_echo_spacing_from_epi_echo_spacing_not_echo_train():
    """EES = PVM_EpiEchoSpacing(ms)/1000 / PPI-accel (default 1), not ACQ_phase_factor.

    PVM_EpiEchoSpacing is Bruker's console echo spacing (EPI only); the old
    1/(EncMatrix*PixelBandwidth) basis returned the ADC sample dwell instead, and
    ACQ_phase_factor is the echo-train factor, not the parallel acceleration.
    """
    p = _p(PVM_EpiEchoSpacing=0.5,        # ms
           ACQ_phase_factor=8)            # must be ignored
    ees = _resolve('EffectiveEchoSpacing', visu=p)
    assert ees == pytest.approx(0.5 / 1000.0)               # accel defaults to 1, not /8


def test_effective_echo_spacing_scales_with_ppi_accel():
    p = _p(PVM_EpiEchoSpacing=0.5, PVM_EncPpiAccel1=2)
    ees = _resolve('EffectiveEchoSpacing', visu=p)
    assert ees == pytest.approx(0.5 / 1000.0 / 2)


def test_effective_echo_spacing_omitted_for_non_epi():
    """PVM_EpiEchoSpacing is absent for non-EPI -> EES (an EPI concept) is omitted."""
    assert _resolve('EffectiveEchoSpacing', visu=_p(VisuAcqPixelBandwidth=200.0)) is None


def test_total_readout_time_is_ees_times_recon_pe_minus_one():
    """FSL/BIDS TotalReadoutTime = EffectiveEchoSpacing * (ReconMatrixPE - 1),
    ReconMatrixPE = PVM_Matrix on the phase axis; PPI-accel defaults to 1."""
    p = _p(PVM_EpiEchoSpacing=0.5, PVM_Matrix=[128, 64],
           VisuAcqGradEncoding=['read_enc', 'phase_enc'],   # phase axis index 1 -> NPE=64
           ACQ_phase_factor=8)                              # must be ignored
    trt = _resolve('TotalReadoutTime', visu=p)
    assert trt == pytest.approx((0.5 / 1000.0) * (64 - 1))


# --- BIDS type safety (schema-validation errors) ----------------------------

def test_mr_transmit_coil_sequence_is_a_string():
    """MRTransmitCoilSequence is BIDS type string (DICOM 0018,9049); a nested
    object (the old dict) is a schema-validation error."""
    val = _resolve('MRTransmitCoilSequence', visu=_p(VisuCoilTransmitName='RF RES 400'))
    assert val == 'RF RES 400'
    assert isinstance(val, str)


def test_inversion_time_scalar_is_seconds_array_is_omitted():
    """InversionTime is a single number in seconds; multi-TI arrays are omitted."""
    assert _resolve('InversionTime', visu=_p(VisuAcqInversionTime=1000.0)) == pytest.approx(1.0)
    # multi-TI (Look-Locker) -> not a single number -> omit
    assert _resolve('InversionTime', visu=_p(VisuAcqInversionTime=[20, 120, 220])) is None
    # not inversion-prepared -> omit
    assert _resolve('InversionTime', visu=_p()) is None


def test_flip_angle_drops_non_positive():
    """BIDS requires FlipAngle > 0; a zero/negative value is omitted."""
    assert _resolve('FlipAngle', visu=_p(VisuAcqFlipAngle=30.0)) == 30.0
    assert _resolve('FlipAngle', visu=_p(VisuAcqFlipAngle=0)) is None


def test_mr_acquisition_type_is_2d_or_3d():
    """MRAcquisitionType must be the string '2D' or '3D'."""
    assert _resolve('MRAcquisitionType', visu=_p(PVM_SpatDimEnum='2D')) == '2D'
    # PV5.1 fallback from the numeric VisuCoreDim
    assert _resolve('MRAcquisitionType', visu=_p(VisuCoreDim=3)) == '3D'


def test_dwell_time_is_inverse_sampling_bandwidth():
    """DwellTime = 1/PVM_EffSWh (per-point), not 1/PixelBandwidth (whole line)."""
    assert _resolve('DwellTime', visu=_p(PVM_EffSWh=100000.0)) == pytest.approx(1e-5)


# --- RepetitionTime for func (M5) -------------------------------------------

def test_repetition_time_emitted_for_every_scan():
    """RepetitionTime is in COMMON_META_REF so the one-shot path emits it (M5).

    It was func-only via FMRI_META_REF, so func sidecars from the one-shot
    conversion path were missing this BIDS-required field.
    """
    assert 'RepetitionTime' in COMMON_META_REF
    assert 'RepetitionTime' not in FMRI_META_REF
    rt = _resolve('RepetitionTime', visu=_p(VisuAcqRepetitionTime=2500.0))
    assert rt == pytest.approx(2.5)                 # ms -> s


def test_func_volume_tr_is_scantime_over_volumes():
    """func RepetitionTime is the volume-to-volume wall-clock time (ScanTime/nvol),
    which exceeds the sequence VisuAcqRepetitionTime for multi-shot/averaged EPI."""
    def _dset(scan_time):
        vp = _p(VisuAcqScanTime=scan_time)
        return SimpleNamespace(get_visu_pars=lambda s, r: vp)

    func = SimpleNamespace(DataType='func', ScanID=1, RecoID=1)
    # 2-shot FAIR-like: 72000 ms / 12 volumes -> 6.0 s (not the 3.0 s sequence TR)
    assert func_volume_tr(_dset(72000.0), func, 12) == pytest.approx(6.0)
    # single volume, non-func, or missing ScanTime -> None (keep the sequence TR)
    assert func_volume_tr(_dset(72000.0), func, 1) is None
    assert func_volume_tr(_dset(72000.0),
                          SimpleNamespace(DataType='anat', ScanID=1, RecoID=1), 12) is None
    assert func_volume_tr(_dset(None), func, 12) is None


def test_common_and_fmri_refs_do_not_share_keys():
    """get_bids_ref_obj raises on duplicate keys when merging 'common' and 'func',
    so the two tables must stay disjoint."""
    assert set(COMMON_META_REF) & set(FMRI_META_REF) == set()


# --- PhaseEncodingDirection axis (M2) ---------------------------------------

@pytest.mark.parametrize('grad_encoding, axis_index', [
    (['phase_enc', 'read_enc'], 0),                       # -> 'i' after loader conversion
    (['read_enc', 'phase_enc'], 1),                       # -> 'j'
    (['read_enc', 'phase_enc', 'slice_enc'], 1),          # -> 'j' (3D)
])
def test_phase_encoding_resolves_axis_index_only(grad_encoding, axis_index):
    """PhaseEncodingDirection resolves the PE axis index (loader maps it to i/j/k).

    The polarity sign (i-/j-/k-) is intentionally NOT emitted: it cannot be
    derived reliably from Bruker parameters and a wrong sign harms distortion
    correction (M2).
    """
    assert _resolve('PhaseEncodingDirection', visu=_p(VisuAcqGradEncoding=grad_encoding)) == axis_index
