"""Unit tests for derived-reconstruction handling (lib/derived.py).

Pure-unit (offline): the module reads element labels off a visu_pars stub.
"""
import numpy as np
import pytest

from brkraw_legacy.lib import derived


class _p(dict):
    """A stub visu_pars: a JCAMPDX's read accessors over a dict."""
    def __init__(self, **params):
        super().__init__(params)

    def get_parameter(self, key):
        from types import SimpleNamespace
        return SimpleNamespace(value=self[key], nested=self[key], val_str=str(self[key]))


#: The real element lists, verbatim from the PV6 lego phantom.
ISA_T1 = ['signal intensity', 'std dev of signal intensity', 'T1 relaxation time',
          'std dev of T1 relaxation time', 'std dev of the fit']
ISA_T2 = ['signal intensity', 'std dev of signal intensity', 'T2 relaxation time',
          'std dev of T2 relaxation time', 'std dev of the fit']
DTI = ['Fractional Anisotropy', 'Trace', 'Intensity', 'Trace Weighted Image',
       'Tensor Component Dxx', 'Tensor Component Dyy', 'Tensor Component Dzz']


@pytest.mark.parametrize(('groups', 'expected'), [
    ([('isa', 5)], True),
    ([('dti', 22)], True),
    ([('isa', 5), ('slice', 5)], True),
    ([('echo', 6), ('slice', 5)], False),
    ([], False),
])
def test_derived_reconstructions_recognised(groups, expected):
    assert derived.is_derived(groups) is expected


@pytest.mark.parametrize(('comments', 'index', 'suffix'), [
    (ISA_T1, 2, 'T1map'),
    (ISA_T2, 2, 'T2map'),
])
def test_isa_map_found_by_label(comments, index, suffix):
    """An ISA fit is a five-volume stack and only one volume is the map.

    Found by label rather than position: the position is stable across the corpus,
    but the label is what states the meaning.
    """
    found = derived.isa_map(_p(VisuFGElemComment=np.array(comments)))
    assert found is not None
    assert (found[0], found[1]) == (index, suffix)


def test_isa_map_scales_milliseconds_to_seconds():
    """BIDS: T1map and T2map are "In seconds (s)". ParaVision fits in ms, so the
    raw element would be off by 1000 -- the corpus T1 map peaks at 6600."""
    _index, _suffix, scale = derived.isa_map(_p(VisuFGElemComment=np.array(ISA_T1)))
    assert scale == pytest.approx(1e-3)
    assert 6600.19 * scale == pytest.approx(6.60019)


def test_dti_stack_has_no_single_map():
    """Twenty-two volumes -- FA, trace, tensor components, eigenvectors -- and no
    single raw BIDS suffix, so the whole stack is a derivative."""
    assert derived.isa_map(_p(VisuFGElemComment=np.array(DTI))) is None


def test_unrecognised_fit_is_not_guessed_at():
    assert derived.isa_map(_p(VisuFGElemComment=np.array(['some other quantity']))) is None
    assert derived.isa_map(_p()) is None


def test_element_comments_tolerates_a_single_string():
    assert derived.element_comments(_p(VisuFGElemComment='T2 relaxation time')) == \
        ['T2 relaxation time']
    assert derived.element_comments(_p()) == []


@pytest.mark.parametrize(('desc', 'is_map'), [
    ([[5, 'FG_ISA', 'T2 relaxation', 0, 2]], True),
    ([[5, 'FG_ISA', 'T2 relaxation', 0, 2], [5, 'FG_SLICE', None, 2, 2]], True),
    ([[5, 'FG_ISA', 'T1 saturation recovery', 0, 2], [5, 'FG_ECHO', None, 2, 1]], False),
    ([[5, 'FG_ISA', 'T2 relaxation', 0, 2], [6, 'FG_MOVIE', 'vtr', 2, 2]], False),
])
def test_a_repeated_fit_is_not_a_single_map(desc, is_map):
    """A fit repeated along another axis has no single map to extract.

    PV5.1 scan 31 is FG_ISA x FG_ECHO -- five maps over five echoes. BIDS has no
    echo- entity for a parametric map, so emitting one produced ENTITY_NOT_IN_RULE,
    and picking one echo silently would discard the rest. The whole stack goes to
    derivatives instead. A slice axis does not count: it makes voxels, not volumes.
    """
    visu = _p(VisuFGOrderDesc=desc,
              VisuFGElemComment=np.array(ISA_T2 if 'T2' in str(desc) else ISA_T1))
    assert (derived.isa_map(visu) is not None) is is_map
