from __future__ import annotations

from .base import BaseHelper, axis_labels, collapse_scale

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..analyzer import ScanInfoAnalyzer


class DataArray(BaseHelper):
    """Word type, intensity scaling and named axes of a reconstruction.

    All three come from `brukerapi`'s derived properties (ADR 0002). What is
    added here is collapsing a uniform per-frame slope/offset to a single
    value, because NIfTI's ``scl_slope``/``scl_inter`` are scalars: with a
    scalar pair the image can stay in its stored word type instead of widening
    to float.

    Dependencies:
        dataset
    """
    def __init__(self, analobj: 'ScanInfoAnalyzer'):
        super().__init__()
        dataset = analobj.dataset
        dtype = dataset.get('numpy_dtype') if dataset is not None else None
        if dtype is None:
            raise ValueError('reconstruction has no image metadata (empty or '
                             'unreadable visu_pars); cannot convert to NIfTI')

        self.data_dtype = dtype
        self.axis_labels = axis_labels(dataset)
        self.data_slope = collapse_scale(dataset.slope)
        self.data_offset = collapse_scale(dataset.offset)

    def get_info(self):
        return {
            'dtype': self.data_dtype,
            'slope': self.data_slope,
            'offset': self.data_offset,
            'axis_labels': self.axis_labels,
            'warns': self.warns
        }
