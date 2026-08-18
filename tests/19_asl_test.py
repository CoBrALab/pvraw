"""Unit tests for ASL control/label resolution (lib/asl.py).

Pure-unit (offline): everything is read off a visu_pars/method stub.

The layouts and element spellings below are all real, taken from PV5.1, PV6.0.1
and PV7.0.0 studies -- the point of the module is that none of them is fixed.
"""
import numpy as np
import pytest

from pvraw.lib import asl
from pvraw.lib.errors import InvalidValueInField


class _p(dict):
    def __init__(self, **params):
        super().__init__(params)

    def get_parameter(self, key):
        from types import SimpleNamespace
        return SimpleNamespace(value=self[key], nested=self[key], val_str=str(self[key]))


def _visu(desc, elements):
    return _p(VisuFGOrderDesc=desc, VisuFGElemComment=np.array(elements))


FAIR_PV6 = ([[3, 'FG_MOVIE', 'Inversion', 0, 1], [2, 'FG_IRMODE', 'Inversion Mode', 1, 1]],
            ['Selective Inversion', 'Non-selective Inversion'])
FAIR_INTERLEAVED2 = ([[2, 'FG_IRMODE', 'Inversion Mode', 0, 1], [16, 'FG_MOVIE', 'Inversion', 1, 1]],
                     ['Selective Inversion', 'Non-selective Inversion'])
FAIR_PV5 = ([[5, 'FG_MOVIE', 'Inversion', 0, 1], [2, 'FG_IRMODE', 'Inversion Mode', 1, 1]],
            ['Selective Inversion Mode', 'Non-selective Inversion Mode'])
FAIR_SHORT = ([[2, 'FG_SLICE', None, 0, 2], [2, 'FG_IRMODE', 'Inversion Mode', 2, 1],
               [6, 'FG_CYCLE', None, 3, 0]],
              ['S TI: 1000.0 ms', 'NS TI: 1000.0 ms'])
CASL = ([[5, 'FG_SLICE', None, 0, 2], [4, 'FG_MOVIE', 'CASL', 2, 1], [1, 'FG_CYCLE', None, 3, 0]],
        ['Label', 'Control', 'Control', 'Control'])


def _pattern(types):
    return ''.join('L' if t == 'label' else 'C' for t in types)


@pytest.mark.parametrize(('layout', 'expected'), [
    (FAIR_PV6, 'CCCLLL'),               # movie varies fastest: blocks
    (FAIR_INTERLEAVED2, 'CL' * 16),     # PVM_FairMode INTERLEAVED2 reverses the axes
    (FAIR_PV5, 'CCCCCLLLLL'),
    (FAIR_SHORT, 'CL' * 6),             # slice axis excluded, cycle axis included
    (CASL, 'LCCC'),                     # CASL names each frame, and label comes first
])
def test_volume_order_follows_the_declared_axes(layout, expected):
    """The layout is not fixed, so the order is derived rather than assumed.

    INTERLEAVED2 is the case that matters: it declares the inversion axis FIRST, so
    the volumes alternate instead of running in blocks. Assuming either shape would
    invert control and label for half the corpus.
    """
    assert _pattern(asl.volume_types(_visu(*layout))) == expected


def test_slice_axis_is_not_a_volume_axis():
    """The converter moves slice to k, so it must not multiply the volume count."""
    assert len(asl.volume_types(_visu(*FAIR_SHORT))) == 12    # 2 irmode x 6 cycle, not x2


@pytest.mark.parametrize('spelling', [
    'Non-selective Inversion', 'Non-selective Inversion Mode', 'NS TI: 1000.0 ms',
])
def test_non_selective_is_the_label_in_every_spelling(spelling):
    """Slice-selective inversion leaves inflowing blood untouched -- that is the
    control. 'S' prefixes both short spellings, so non-selective must win."""
    types = asl.volume_types(_visu(
        [[2, 'FG_IRMODE', 'Inversion Mode', 0, 1]], ['Selective Inversion', spelling]))
    assert types == ['control', 'label']


def test_unknown_element_labels_raise_rather_than_guess():
    """Falling back to axis order would silently invert the perfusion signal on any
    INTERLEAVED2 scan, so an unrecognised label is an error."""
    with pytest.raises(InvalidValueInField, match='Refusing to fall back'):
        asl.volume_types(_visu([[2, 'FG_IRMODE', 'x', 0, 1]], ['Alpha', 'Beta']))


def test_element_count_must_match_the_axis():
    with pytest.raises(InvalidValueInField, match='refusing to guess'):
        asl.volume_types(_visu([[3, 'FG_IRMODE', 'x', 0, 1]],
                               ['Selective Inversion', 'Non-selective Inversion']))


def test_non_asl_scans_are_left_alone():
    assert asl.volume_types(_visu([[6, 'FG_ECHO', None, 0, 1]], ['a', 'b'])) is None


@pytest.mark.parametrize(('method', 'expected'), [
    ('Bruker:FAIR_EPI', 'PASL'), ('FAIR_RARE', 'PASL'),
    ('Bruker:CASL_EPI', 'CASL'), ('Bruker:FLASH', None), ('', None),
])
def test_labeling_type_from_the_method_name(method, expected):
    """No parameter states it, and no ParaVision version present ships pCASL, so
    PCASL is unreachable rather than guessed at."""
    assert asl.labeling_type(method) == expected


def test_sidecar_states_what_the_sequence_does_not_have():
    """These are constants because ParaVision has no such module -- saying false is
    a fact about the sequence, not a placeholder. BolusCutOffFlag false is also what
    keeps BolusCutOffDelayTime and Technique from being required."""
    fields = asl.sidecar_fields('Bruker:FAIR_EPI', _p(), _p(), ['control', 'label'])
    assert fields['ArterialSpinLabelingType'] == 'PASL'
    assert fields['BackgroundSuppression'] is False
    assert fields['VascularCrushing'] is False
    assert fields['BolusCutOffFlag'] is False
    assert fields['M0Type'] == 'Absent'


def test_total_acquired_pairs_counts_usable_pairs():
    """CASL in Dynamic mode sets label and control counts independently -- the
    corpus has one label against three controls -- so this is min(), not half the
    volume count."""
    fields = asl.sidecar_fields('Bruker:CASL_EPI', _p(), _p(),
                                ['label', 'control', 'control', 'control'])
    assert fields['TotalAcquiredPairs'] == 1


def test_repetition_time_preparation_survives_an_array_valued_tr():
    """`a or b` raises on an array, and VisuAcqRepetitionTime is one on a
    variable-TR scan. That aborted every ASL conversion after the image was already
    written, leaving an orphan NIfTI with no sidecar."""
    visu = _p(VisuAcqRepetitionTime=np.array([1000.0, 2000.0]))
    method = _p(PVM_RepetitionTime=3000.0)
    fields = asl.sidecar_fields('FAIR_EPI', method, visu, ['control', 'label'])
    assert fields['RepetitionTimePreparation'] == pytest.approx(3.0)


@pytest.mark.parametrize(('method_params', 'expected'), [
    ({'PVM_SpatResol': np.array([0.3, 0.3]), 'PVM_SliceThick': 1.5}, [0.3, 0.3, 1.5]),
    ({'PVM_SpatResol': np.array([0.2, 0.2, 0.2]), 'PVM_SliceThick': 40.0}, [0.2, 0.2, 0.2]),
])
def test_acquisition_voxel_size_does_not_use_the_3d_slab(method_params, expected):
    """In 3D, PVM_SliceThick is the whole slab -- 40 mm for a 0.2 mm voxel here --
    so the third value must come from PVM_SpatResol instead."""
    assert asl.acquisition_voxel_size(_p(**method_params)) == pytest.approx(expected)
