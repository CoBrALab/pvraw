from __future__ import annotations

from typing import TYPE_CHECKING

from brkraw_legacy.lib.utils import get_value

from .base import BaseHelper

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
    def __init__(self, analobj: ScanInfoAnalyzer):
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

        # One distance per pack, from `brukerapi` (ADR 0002): the step its
        # affine places the voxels with. VisuCoreFrameThickness is not that --
        # for a 3D acquisition it is the *slab* thickness, which reported 12 mm
        # for a 0.125 mm isotropic volume. That is what this used to read, and
        # 214 of the 1739 reconstructions in resources/testdata disagreed with
        # their own affine because of it; upstream exposes the number since
        # 0.4.3 (isi-nmr/brukerapi-python#177).
        self.slice_distances_each_pack = self._pack_distances(analobj.dataset, visu_pars)

        self.slice_order_scheme = get_value(method, "PVM_ObjOrderScheme") if method else None
        disk_slice_order = get_value(visu_pars, "VisuCoreDiskSliceOrder") or 'normal'
        self.is_reverse = 'reverse' in str(disk_slice_order)

    def _pack_distances(self, dataset, visu_pars):
        """Centre-to-centre slice step of each pack, in mm.

        A reconstruction whose frames are not spatial has no affine, and
        ``slice_distance`` says so rather than inventing one. There the
        parameters are all there is -- collapsing any per-frame
        VisuCoreFrameThickness (an ISA parametric map such as an MGE T2* map
        stores one per frame) to a scalar so the resolution is not ragged.
        """
        try:
            return [float(distance) for distance in dataset.slice_distance]
        except Exception:
            distance = get_value(visu_pars, "VisuCoreSlicePacksSliceDist")
            if distance is None:
                distance = get_value(visu_pars, "VisuCoreFrameThickness")
            distance = distance[0] if hasattr(distance, '__len__') and len(distance) else distance
            return [distance] * self.num_slice_packs

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
