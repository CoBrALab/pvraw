from __future__ import annotations

import numpy as np

from brkraw_legacy.lib.utils import get_value

from .base import BaseHelper

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..analyzer import ScanInfoAnalyzer


class Image(BaseHelper):
    """In-plane geometry of a reconstruction: matrix, field of view, resolution.

    Dependencies:
        visu_pars
    """
    def __init__(self, analobj: 'ScanInfoAnalyzer'):
        super().__init__()
        visu_pars = analobj.visu_pars

        self.dim = int(get_value(visu_pars, "VisuCoreDim"))
        # one entry per encoded axis, even for a 1D reconstruction
        self.dim_desc = [str(d) for d in np.atleast_1d(get_value(visu_pars, "VisuCoreDimDesc"))]
        fov = get_value(visu_pars, "VisuCoreExtent")
        shape = get_value(visu_pars, "VisuCoreSize")
        self.resolusion = np.divide(fov, shape).tolist() if (fov is not None and shape is not None) else None
        self.field_of_view = fov
        self.shape = shape

        if self.dim > 3:
            self._warn('Image dimension exceeds 3. Ensure that handling of higher dimensions is supported and correctly implemented.')
        def message(x): return f"The axis of the image includes '{x}' dimension, which is not limited to spatial types."
        for d in self.dim_desc:
            if d != 'spatial':
                self._warn(message(d))

    def get_info(self):
        return {
            'dim': self.dim,
            'dim_desc': self.dim_desc,
            'shape': self.shape,
            'resolution': self.resolusion,
            'field_of_view': self.field_of_view,
            'unit': 'mm',
            'warns': self.warns
        }
