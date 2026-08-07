from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from brkraw_legacy.lib.utils import get_value

from .base import BaseHelper

if TYPE_CHECKING:
    from ..analyzer import ScanInfoAnalyzer


class Diffusion(BaseHelper):
    """Diffusion b-values and gradient directions, read from the scan's ``method``.

    Dependencies:
        method
    """
    def __init__(self, analobj: ScanInfoAnalyzer):
        super().__init__()
        method = analobj.method

        self.bvals = None
        self.bvecs = None
        if method:
            self._set_params(method)
        else:
            self._warn("Failed to fetch 'bvals' and 'bvecs' information because the 'method' file is missing from 'analobj'.")

    def _set_params(self, method):
        bvals = get_value(method, 'PVM_DwEffBval')
        bvecs = get_value(method, 'PVM_DwGradVec')
        if bvals is not None:
            self.bvals = np.array([bvals]) if np.size(bvals) < 2 else np.array(bvals)
        if bvecs is not None:
            self.bvecs = self._L2_norm(np.asarray(bvecs).T)

    @staticmethod
    def _L2_norm(bvecs):
        # Normalize bvecs
        bvecs_axis = 0
        bvecs_L2_norm = np.atleast_1d(np.linalg.norm(bvecs, 2, bvecs_axis))
        bvecs_L2_norm[bvecs_L2_norm < 1e-15] = 1
        bvecs = bvecs / np.expand_dims(bvecs_L2_norm, bvecs_axis)
        return bvecs

    def get_info(self):
        return {
            'bvals': self.bvals,
            'bvecs': self.bvecs,
            'warns': self.warns
        }
