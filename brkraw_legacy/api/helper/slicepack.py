from __future__ import annotations


from brkraw_legacy.lib.utils import get_value

from .base import BaseHelper

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..analyzer import ScanInfoAnalyzer


class SlicePack(BaseHelper):
    """How a reconstruction's slices are grouped, and how far apart they are.

    Slice packages are geometry: more than one means the reconstruction holds
    several distinct orientations and cannot be a single NIfTI, and each pack's
    slice count and distance set the third column of its affine.

    Dependencies:
        dataset
        method
        visu_pars
    """
    def __init__(self, analobj: 'ScanInfoAnalyzer'):
        super().__init__()
        method = analobj.method
        visu_pars = analobj.visu_pars

        # How the frames divide into packages is `brukerapi`'s to say (ADR 0002,
        # amended): it reads VisuCoreSlicePacksSlices where ParaVision writes it
        # and derives the division where it does not -- PV5.1 never writes it,
        # and deriving it from the per-slice phase-encoding directions instead
        # split a 3x5 tripilot into fifteen single-slice packages.
        packages = analobj.dataset.slice_packages_index() or [(0, None)]
        self.num_slice_packs = len(packages)
        self.num_slices_each_pack = [
            count if count is not None else get_value(visu_pars, "VisuCoreFrameCount")
            for _, count in packages
        ]

        # One distance per pack, as a scalar: a derived reconstruction whose
        # frames are a non-spatial group (e.g. an ISA parametric map such as an
        # MGE T2* map) can store VisuCoreFrameThickness per frame, which would
        # otherwise leave a ragged resolution. Collapse any per-frame list to
        # the single slice thickness. The affine no longer reads this -- it is
        # kept because the NIfTI header and the BIDS layer report it.
        distance = get_value(visu_pars, "VisuCoreSlicePacksSliceDist")
        if distance is None:
            distance = get_value(visu_pars, "VisuCoreFrameThickness")
        distance = distance[0] if hasattr(distance, '__len__') and len(distance) else distance
        self.slice_distances_each_pack = [distance] * self.num_slice_packs

        self.slice_order_scheme = get_value(method, "PVM_ObjOrderScheme") if method else None
        disk_slice_order = get_value(visu_pars, "VisuCoreDiskSliceOrder") or 'normal'
        self.is_reverse = 'reverse' in str(disk_slice_order)

    def get_info(self):
        return {
            'num_slice_packs': self.num_slice_packs,
            'num_slices_each_pack': self.num_slices_each_pack,
            'slice_distances_each_pack': self.slice_distances_each_pack,
            'slice_distance_unit': 'mm',
            'slice_order_scheme': self.slice_order_scheme,
            'reverse_slice_order': self.is_reverse,
            'warns': self.warns
        }
