"""Slice-distance regression tests (api.helper.slicepack).

Pure-unit (offline). The reported slice distance must be the centre-to-centre
step the affine actually places voxels with, not ``VisuCoreFrameThickness``.

For a 3D acquisition ``VisuCoreFrameThickness`` is the *slab* thickness, so
reading it reported e.g. 12 mm for a 0.125 mm isotropic volume -- the same
thickness-vs-spacing confusion ADR 0002's amendment fixed in the affine, left
behind in what ``info`` and the study header report. 214 of the 1739
reconstructions in ``resources/testdata`` were affected.

``brukerapi``'s ``resolution[2]`` is not the answer either: it is 0 for an ISA
parametric map whose third dimension is not spatial, and a cross-package
diagonal when the reconstruction holds several slice packages. The affine is
correct in both cases because it is built per package from measured positions.
"""
import numpy as np
import pytest

from brkraw_legacy.api.helper.slicepack import SlicePack


class _Params(dict):
    """A JCAMPDX stand-in exposing the accessors ``get_value`` uses."""
    def get_parameter(self, key):
        return _Value(self[key])

    def keys(self):
        return super().keys()


class _Value:
    def __init__(self, value):
        self.value = value
        self.val_str = str(value)
        self.nested = value


class _Dataset:
    """A `brukerapi` Dataset stand-in: packages and their affines."""
    def __init__(self, packages, steps, raises=False):
        self._packages, self._steps, self._raises = packages, steps, raises

    def slice_packages_index(self):
        return self._packages

    def affine_of_package(self, index):
        if self._raises:
            raise AttributeError("'Dataset' object has no attribute 'affine'")
        affine = np.eye(4)
        affine[:3, 2] = [0, 0, self._steps[index]]
        return affine


class _Analobj:
    def __init__(self, dataset, visu_pars, method=None):
        self.dataset, self.visu_pars, self.method = dataset, visu_pars, method


def _slicepack(dataset, visu_pars, method=None):
    return SlicePack(_Analobj(dataset, _Params(visu_pars), _Params(method or {})))


def test_3d_slab_thickness_is_not_reported_as_slice_distance():
    """A 3D acquisition stores the slab thickness in VisuCoreFrameThickness.
    The affine's step is the plane spacing, and that is what must be reported."""
    info = _slicepack(
        _Dataset(packages=[(0, 96)], steps=[0.125]),
        {'VisuCoreFrameThickness': 12.0, 'VisuCoreFrameCount': 96},
    ).get_info()
    assert info['slice_distances_each_pack'] == pytest.approx([0.125])


def test_each_package_reports_its_own_distance():
    """Slice packages may differ in spacing, so each is measured separately."""
    info = _slicepack(
        _Dataset(packages=[(0, 5), (5, 5), (10, 5)], steps=[1.0, 2.0, 0.5]),
        {'VisuCoreFrameThickness': 1.0},
    ).get_info()
    assert info['slice_distances_each_pack'] == pytest.approx([1.0, 2.0, 0.5])
    assert info['num_slice_packs'] == 3


def test_falls_back_to_parameters_when_the_affine_is_unavailable():
    """A reconstruction without geometry (non-spatial frames) has no affine;
    the parameter read is still better than reporting nothing."""
    info = _slicepack(
        _Dataset(packages=[(0, 10)], steps=[1.0], raises=True),
        {'VisuCoreSlicePacksSliceDist': 1.4},
    ).get_info()
    assert info['slice_distances_each_pack'] == pytest.approx([1.4])


def test_per_frame_thickness_does_not_leave_a_ragged_fallback():
    """An ISA parametric map can store VisuCoreFrameThickness per frame. When
    the affine is unavailable the fallback must still collapse to one scalar."""
    info = _slicepack(
        _Dataset(packages=[(0, 3)], steps=[1.0], raises=True),
        {'VisuCoreFrameThickness': [0.8, 0.8, 0.8]},
    ).get_info()
    assert info['slice_distances_each_pack'] == pytest.approx([0.8])
