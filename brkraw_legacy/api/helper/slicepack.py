from __future__ import annotations

import numpy as np

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

        # One distance per pack, measured from that pack's own affine: the
        # length of its third column is the centre-to-centre step the voxels
        # are actually placed with. VisuCoreFrameThickness is not that -- for a
        # 3D acquisition it is the *slab* thickness, which reported 12 mm for a
        # 0.125 mm isotropic volume (214 of 1739 reconstructions in
        # resources/testdata). It is the thickness-vs-spacing confusion ADR
        # 0002's amendment fixed in the affine, left behind in what `info` and
        # the study header report.
        #
        # `brukerapi`'s resolution[2] is not the answer either: 0 where the
        # third dimension is not spatial (ISA parametric maps), and a
        # cross-package diagonal where there are several packages.
        self.slice_distances_each_pack = [
            self._pack_distance(analobj.dataset, index, visu_pars)
            for index in range(self.num_slice_packs)
        ]

        self.slice_order_scheme = get_value(method, "PVM_ObjOrderScheme") if method else None
        disk_slice_order = get_value(visu_pars, "VisuCoreDiskSliceOrder") or 'normal'
        self.is_reverse = 'reverse' in str(disk_slice_order)

    @staticmethod
    def _pack_distance(dataset, index, visu_pars):
        """One slice package's centre-to-centre step, in mm.

        From the package's affine where there is one. A reconstruction whose
        frames are not spatial has no affine, and there the parameters are all
        there is -- collapsing any per-frame VisuCoreFrameThickness (an ISA
        parametric map such as an MGE T2* map stores one per frame) to a scalar
        so the resolution does not come out ragged.
        """
        try:
            return float(np.linalg.norm(np.asarray(dataset.affine_of_package(index))[:3, 2]))
        except Exception:
            distance = get_value(visu_pars, "VisuCoreSlicePacksSliceDist")
            if distance is None:
                distance = get_value(visu_pars, "VisuCoreFrameThickness")
            return distance[0] if hasattr(distance, '__len__') and len(distance) else distance

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
