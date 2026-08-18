"""Unit tests for slice-axis normalization (app.tonifti.base).

Pure-unit (offline): the slice axis is placed at position k (2), and a size-1
slice axis is inserted for a 2D acquisition that stores none, so a single-slice
scan is written as a conventional 3D NIfTI volume rather than a 2D image.
"""
import numpy as np

from pvraw.app.tonifti.base import BaseMethods


def test_single_slice_2d_gains_a_size1_slice_axis():
    """A single-slice 2D acquisition (two spatial axes, no frame groups) is
    promoted to (X, Y, 1) so it is written as a 3D volume, not a 2D image."""
    labels = ['spatial', 'spatial']
    out = BaseMethods._normalize_slice_axis(np.zeros((4, 3)), labels)
    assert out.shape == (4, 3, 1)
    assert labels == ['spatial', 'spatial', 'slice']


def test_3d_acquisition_is_left_unchanged():
    """A 3D acquisition already carries three spatial axes; no slice is added."""
    labels = ['spatial', 'spatial', 'spatial']
    out = BaseMethods._normalize_slice_axis(np.zeros((4, 3, 2)), labels)
    assert out.shape == (4, 3, 2)
    assert labels == ['spatial', 'spatial', 'spatial']


def test_2d_with_frame_group_gets_slice_before_the_frames():
    """A 2D acquisition whose extra axis is a frame group (echo/cycle/...) gets
    the implicit slice inserted at position 2, ahead of the frame axis."""
    labels = ['spatial', 'spatial', 'echo']
    out = BaseMethods._normalize_slice_axis(np.zeros((4, 3, 5)), labels)
    assert out.shape == (4, 3, 1, 5)
    assert labels == ['spatial', 'spatial', 'slice', 'echo']


def test_existing_slice_axis_is_moved_to_position_2():
    """An explicit slice frame group not already at k is swapped into place."""
    labels = ['spatial', 'spatial', 'echo', 'slice']
    out = BaseMethods._normalize_slice_axis(np.zeros((4, 3, 5, 6)), labels)
    assert out.shape == (4, 3, 6, 5)
    assert labels == ['spatial', 'spatial', 'slice', 'echo']
