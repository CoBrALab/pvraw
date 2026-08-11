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


def test_gradient_set_type_extracts_the_bis_name():
    """GradientSetType is the '#$Name,' component of the BIS hardware string
    (FILE_FORMAT.md 4.2), not the whole blob of serial numbers and per-coil
    calibration. Reachable since brukerapi 0.4.5 loads `configscan`."""
    bis = ('$Bis,1,20070906,2048,GRADSYS,1#$Production,W3307165,0082,00,08,BFR,'
           '20130829#$Name,B-GA12SHP FOR BC70/20 TYP 2#$GradSystem,1.0,27,S116,0,,1')
    ref = COMMON_META_REF['GradientSetType']
    assert meta_get_value(ref, _p(CONFIG_SCAN_gradient_system=bis)) == \
        'B-GA12SHP FOR BC70/20 TYP 2'
    # A nameless BIS string omits the field rather than emitting the blob.
    assert meta_get_value(ref, _p(CONFIG_SCAN_gradient_system='$Bis,1')) is None
    # No configscan at all (PV5.1, or an export without one) omits the field.
    assert meta_get_value(ref, _p()) is None


def test_index_that_misses_the_parameter_shape_omits_the_field():
    """An index mapping whose index misses the value omits the field (#80).

    Both real failure modes from lego_phantom: TotalReadoutTime's NPE indexes
    PVM_Matrix at the phase-encode position, which VisuAcqGradEncoding can
    place at 2 while PVM_Matrix has 2 elements (scans 30/34); and a
    scalar-valued parameter is not subscriptable at all (scans 35/39). Either
    used to raise out of _parse_json and kill the whole sidecar.
    """
    from brkraw_legacy.lib.utils import meta_check_index

    # index out of range: phase_enc resolves to position 2, val has 2 elements
    out_of_range = {'key': 'PVM_Matrix',
                    'idx': {'key': 'VisuAcqGradEncoding', 'where': 'phase_enc'}}
    params = _p(PVM_Matrix=[128, 128],
                VisuAcqGradEncoding=['read_enc', 'slice_enc', 'phase_enc'])
    assert meta_check_index(out_of_range, params) is None

    # scalar value: not subscriptable
    assert meta_check_index({'key': 'PVM_Matrix', 'idx': 1}, _p(PVM_Matrix=128)) is None

    # the guard must not eat the working case
    assert meta_check_index({'key': 'PVM_Matrix', 'idx': 1},
                            _p(PVM_Matrix=[128, 96])) == 96


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


# --- PhaseEncodingAxis (M2) --------------------------------------------------

@pytest.mark.parametrize('grad_encoding, axis_index', [
    (['phase_enc', 'read_enc'], 0),                       # -> 'i' after loader conversion
    (['read_enc', 'phase_enc'], 1),                       # -> 'j'
    (['read_enc', 'phase_enc', 'slice_enc'], 1),          # -> 'j' (3D)
])
def test_phase_encoding_resolves_axis_index_only(grad_encoding, axis_index):
    """The mapping resolves the PE axis index (the loader turns it into i/j/k).

    It is emitted as the non-BIDS key ``PhaseEncodingAxis``, never as BIDS
    ``PhaseEncodingDirection``: that field has no unsigned value, so a bare 'j'
    would assert positive polarity. The sign cannot be derived from Bruker
    parameters alone, and a wrong one harms distortion correction (M2).
    """
    assert _resolve('PhaseEncodingAxis', visu=_p(VisuAcqGradEncoding=grad_encoding)) == axis_index


# --- gap fields: mappings the corpus does not exercise end to end ------------

def test_string_parameters_reach_equations():
    """Bruker states most yes/no and mode parameters as enums, so an equation must
    be able to read a string. They used to be replaced with None before eval."""
    assert meta_check_express({'S': 'X', 'Equation': "S == 'On'"}, _p(), _p(X='On'), _p()) is True


@pytest.mark.parametrize(('params', 'expected'), [
    ({'PVM_MagTransOnOff': 'On'}, True),
    ({'PVM_MagTransOnOff': 'Off'}, False),
    ({'PVM_SatTransOnOff': 'On'}, True),        # PV360 spelling
    ({}, None),
])
def test_mt_state(params, expected):
    assert _resolve('MTState', method=_p(**params)) is expected


@pytest.mark.parametrize(('spoiling', 'state', 'type_'), [
    ('NotSpoiled', False, None),
    ('RFSpoiled', True, 'RF'),
    ('GradientSpoiled', True, 'GRADIENT'),
    ('RFAndGradientSpoiled', True, 'COMBINED'),
])
def test_spoiling_enum_maps_onto_the_bids_enum(spoiling, state, type_):
    """An unspoiled sequence has no spoiling *type* -- only a False state."""
    assert _resolve('SpoilingState', visu=_p(VisuAcqSpoiling=spoiling)) is state
    assert _resolve('SpoilingType', visu=_p(VisuAcqSpoiling=spoiling)) == type_


@pytest.mark.parametrize(('params', 'expected'), [
    ({'RFSpoiling': 'Yes'}, 117.0),
    ({'RFSpoiling': 'No'}, None),
    ({'RFSpoilerOnOff': 'On'}, 117.0),          # PV5.1 spelling
    ({}, None),
])
def test_rf_spoiling_phase_increment(params, expected):
    """117 degrees is fixed in Bruker's own sequence source, not in any parameter,
    so it may only be emitted where the sequence declares RF spoiling on."""
    assert _resolve('SpoilingRFPhaseIncrement', method=_p(**params)) == expected


@pytest.mark.parametrize(('param', 'spoil', 'dur', 'ampl', 'res_mm'), [
    # FLASH family: ReadSpoiler, `spoil` referenced to the read voxel size
    ('ReadSpoiler', 2.0, 0.90021978021978, 50.0, 0.15625),        # PV6 scan 3, FLASH
    ('ReadSpoiler', 2.0, 1.732, 25.987868943989, 0.15625),        # PV6 scan 6, MGE
    ('ReadSpoiler', 2.0, 2.042, 11.0212999537192, 0.3125),        # PV7 scan 6, B1Map
    ('ReadSpoiler', 2.0, 2.05764521193093, 50.0, 0.068359375),    # PV7 scan 19, FLASH
    # RARE family: RepetitionSpoiler, `spoil` referenced to slice thickness
    ('RepetitionSpoiler', 4.0, 0.75, 9.37728937728938, 2.0),      # PV6 scan 7, MSME
    ('RepetitionSpoiler', 8.0, 3.0, 8.08387015283567, 1.16),      # PV6 scan 10, RAREVTR
    ('RepetitionSpoiler', 2.5, 0.45, 19.5360195360195, 1.0),      # PV7 scan 17, FAIR_RARE
])
def test_spoiler_moment_reproduces_brukers_own_cycles_per_pixel(param, spoil, dur, ampl, res_mm):
    """Closed-loop check of the spoiler derivation against Bruker's stated intent.

    The spoiler struct is (automatic, spoil, dur, ampl), where ``spoil`` is the
    dephasing the sequence asks for in CYCLES PER PIXEL -- an independent statement
    of the same physics that nothing in our derivation uses. If the moment is right,

        cycles = (gamma/2pi) * moment * voxel_size

    must return that number. It does, exactly, on every corpus scan declaring either
    spoiler. That is what makes SpoilingGradientMoment safe to emit at all: nothing
    records the moment itself, so without this the derivation would be a guess.
    """
    gamma = 42577.478   # Hz/mT
    # 28437.5 Hz/mm is what every corpus scan reports: a 667.9 mT/m gradient set.
    method = _p(**{param: [['Yes', spoil, dur, ampl]]}, PVM_GradCalConst=28437.5)

    duration = _resolve('SpoilingGradientDuration', method=method)
    moment = _resolve('SpoilingGradientMoment', method=method)

    assert duration == pytest.approx(dur / 1000.0)
    assert gamma * moment * (res_mm / 1000.0) == pytest.approx(spoil, rel=1e-3)


def test_spoiler_fields_absent_when_only_a_slice_spoiler_exists():
    """SliceSpoiler fires before excitation -- a pre-excitation crusher, not the
    residual-transverse spoiler BIDS means. EPI, FISP, UTE and SPIRAL declare only
    that one, and must emit neither field rather than the wrong lobe."""
    method = _p(SliceSpoiler=[['Yes', 2, 0.225, 31.25]], PVM_GradCalConst=28437)
    assert _resolve('SpoilingGradientDuration', method=method) is None
    assert _resolve('SpoilingGradientMoment', method=method) is None


@pytest.mark.parametrize(('on', 'mode', 'suppressed', 'technique'), [
    ('On', 'VAPOR', True, 'VAPOR'),
    ('On', 'CHESS', True, 'CHESS'),
    ('On', 'NO_SUPPRESSION', False, None),   # 14 real files look like this
    ('Off', 'VAPOR', False, None),           # and 2 look like this
    ('Off', 'NO_SUPPRESSION', False, None),
])
def test_water_suppression_needs_both_the_flag_and_the_mode(on, mode, suppressed, technique):
    """The flag and the mode disagree in real data, so neither alone is safe."""
    params = {'PVM_WsOnOff': on, 'PVM_WsMode': mode}
    assert _resolve('WaterSuppression', method=_p(**params)) is suppressed
    assert _resolve('WaterSuppressionTechnique', method=_p(**params)) == technique


@pytest.mark.parametrize(('pack_del', 'expected'), [
    (5.0, 0.005), (0.001, None), (0, None),   # ParaVision floors the parameter at 0.001 ms
])
def test_delay_time_treats_the_parameter_floor_as_no_delay(pack_del, expected):
    assert _resolve('DelayTime', method=_p(PackDel=pack_del)) == expected


@pytest.mark.parametrize(('module', 'expected'), [('On', 0.002), ('Off', None)])
def test_delay_after_trigger_is_gated_on_the_trigger_module(module, expected):
    """PVM_TriggerDelay keeps its last value when the module is off."""
    assert _resolve('DelayAfterTrigger',
                    method=_p(PVM_TriggerModule=module, PVM_TriggerDelay=2)) == expected


@pytest.mark.parametrize(('ppi', 'out_of_plane', 'technique'), [
    ([1, 1], None, None),           # 2D, unaccelerated: no slice axis at all
    ([1, 2], None, 'GRAPPA'),       # 2D, accelerated in plane
    ([1, 1, 1], 1.0, None),         # 3D, unaccelerated
    ([1, 1, 2], 2.0, 'GRAPPA'),     # 3D, accelerated through plane
])
def test_parallel_imaging_from_encppi(ppi, out_of_plane, technique):
    """PVM_EncPpi has one element per logical axis: 2 in 2D, 3 in 3D."""
    assert _resolve('ParallelReductionFactorOutOfPlane',
                    method=_p(PVM_EncPpi=np.array(ppi))) == out_of_plane
    assert _resolve('ParallelAcquisitionTechnique',
                    method=_p(PVM_EncPpi=np.array(ppi))) == technique


@pytest.mark.parametrize(('params', 'excitation', 'preparation'), [
    ({'PVM_RepetitionTime': 100}, 0.1, None),
    # MDEFT: PVM_RepetitionTime IS the segment TR, so the excitation TR is EchoRepTime
    ({'PVM_RepetitionTime': 4000, 'SegmRepTime': 4000, 'EchoRepTime': 15}, 0.015, 4.0),
])
def test_repetition_times_of_a_prepared_sequence(params, excitation, preparation):
    assert _resolve('RepetitionTimeExcitation', method=_p(**params)) == excitation
    assert _resolve('RepetitionTimePreparation', method=_p(**params)) == preparation


@pytest.mark.parametrize(('te', 'te1', 'te2'), [
    ([1.537, 5.537], 0.001537, 0.005537),   # real PV5.1 FieldMap values
    ([4.0], None, None),                    # single echo is not a phase-difference map
])
def test_fieldmap_echo_times(te, te1, te2):
    """EffectiveTE, not PVM_EchoTime -- the latter is echo *spacing* for FieldMap."""
    from brkraw_legacy.lib.reference import FIELDMAP_META_REF

    def resolve(field):
        return meta_get_value(FIELDMAP_META_REF[field], _p(),
                              _p(EffectiveTE=np.array(te)), _p())

    assert resolve('EchoTime1') == te1
    assert resolve('EchoTime2') == te2


# --- dummy scans, across ParaVision versions ---------------------------------

@pytest.mark.parametrize(('params', 'expected'), [
    ({'PVM_DummyScans': 4}, 4),      # PV6/PV7/PV360
    ({'NDummyScans': 2}, 2),         # PV5.1: the EPI method declares it locally
    ({'PVM_DummyScans': 4, 'NDummyScans': 2}, 4),   # prefer the PVM_ form
    ({}, None),
])
def test_discarded_volumes_falls_back_to_the_pv51_parameter(params, expected):
    """PVM_DummyScans does not exist on PV5.1, where the name is NDummyScans.

    Covered here because no study in the corpus converts a func scan, so the
    end-to-end runs never reach this key: it is merged for bold/cbv/epi only.
    """
    assert meta_get_value(FMRI_META_REF['NumberOfVolumesDiscardedByScanner'],
                          _p(), _p(**params), _p()) == expected


# --- deprecated-for-func handling -------------------------------------------

@pytest.mark.parametrize(('modality', 'expected'), [
    ('bold', False), ('cbv', False), ('epi', False),   # deprecated for func
    ('T2w', True), ('dwi', True),                      # still optional elsewhere
])
def test_acquisition_duration_dropped_only_for_func(modality, expected, tmp_path):
    """BIDS deprecates AcquisitionDuration for func, and only for func.

    The corpus studies convert no func scans, so nothing else covers this.
    """
    import json

    from brkraw_legacy.lib.utils import get_bids_ref_obj

    template = tmp_path / 'ref.json'
    template.write_text(json.dumps({
        'common': {'AcquisitionDuration': {'T': 'VisuAcqScanTime', 'Equation': 'T/1000'}},
        'func': {'VolumeTiming': None},
    }))
    ref = get_bids_ref_obj(str(template), SimpleNamespace(modality=modality))
    assert ('AcquisitionDuration' in ref) is expected
