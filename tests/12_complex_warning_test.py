"""Unit test for the COMPLEX_IMAGE conversion warning (app.tonifti.base).

Pure-unit (offline): the detection is a static check over the axis labels.
"""
import warnings

import pytest

from pvraw.app.tonifti.base import BaseMethods


def test_complex_axis_warns():
    """A 'complex' frame axis warns that part- splitting is not automated (M4)."""
    with pytest.warns(UserWarning, match="part-real"):
        BaseMethods._warn_if_complex(['x', 'y', 'slice', 'complex'])


def test_non_complex_axis_is_silent():
    """Ordinary (non-complex) data emits no complex warning."""
    with warnings.catch_warnings():
        warnings.simplefilter('error')          # any warning becomes an error
        BaseMethods._warn_if_complex(['x', 'y', 'slice', 'echo'])
        BaseMethods._warn_if_complex(None)
