from __future__ import annotations

import numpy as np

from brkraw_legacy.lib.utils import get_value

from .base import BaseHelper, frame_groups, is_all_element_same

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
        groups = frame_groups(analobj.dataset)

        # A reconstruction whose frames are not typed -- no frame groups at all,
        # or a derived map (ISA/DTI) that carries VisuFGOrderDesc without a
        # VisuCoreFrameType -- has one pack spanning every frame.
        if get_value(visu_pars, "VisuCoreFrameType") is None or not groups:
            num_slice_packs = 1
            num_slices_each_pack = [get_value(visu_pars, "VisuCoreFrameCount")]
            slice_distances_each_pack = [get_value(visu_pars, "VisuCoreFrameThickness")] \
                if int(get_value(visu_pars, "VisuCoreDim")) > 1 else []
        else:
            if get_value(visu_pars, "VisuVersion") == 1:
                parser = self._parse_legacy
            else:
                parser = self._parse_6to360

            num_slice_packs, num_slices_each_pack, slice_distances_each_pack = parser(visu_pars, groups)
            if len(slice_distances_each_pack):
                for i, d in enumerate(slice_distances_each_pack):
                    # a per-frame thickness array is collapsed below, not defaulted here
                    if np.ndim(d) == 0 and d == 0:
                        slice_distances_each_pack[i] = get_value(visu_pars, "VisuCoreFrameThickness")
            if not len(num_slices_each_pack):
                num_slices_each_pack = [1]

        self.num_slice_packs = num_slice_packs
        self.num_slices_each_pack = num_slices_each_pack
        # One distance per pack, as a scalar: a derived reconstruction whose
        # frames are a non-spatial group (e.g. an ISA parametric map such as an
        # MGE T2* map) can store VisuCoreFrameThickness per frame, which would
        # otherwise leave a ragged (x, y, z) resolution and crash affine
        # composition. Collapse any per-frame list to the single slice thickness.
        self.slice_distances_each_pack = [
            d[0] if hasattr(d, '__len__') else d
            for d in slice_distances_each_pack
        ]
        self.slice_order_scheme = get_value(method, "PVM_ObjOrderScheme") if method else None

        disk_slice_order = get_value(visu_pars, "VisuCoreDiskSliceOrder") or 'normal'
        self.is_reverse = 'reverse' in str(disk_slice_order)
        if get_value(visu_pars, "VisuVersion") not in (1, 3, 4, 5):
            self._warn(f'Parameters with current Visu Version has not been tested: '
                       f'v{get_value(visu_pars, "VisuVersion")}')

    def _parse_legacy(self, visu_pars, groups):
        """Slice description for ParaVision < 6.

        The pack count comes from the per-pack phase-encoding directions, and
        the slices are shared out evenly between the packs.
        """
        num_slice_packs = 1
        phase_enc_dir = get_value(visu_pars, "VisuAcqImagePhaseEncDir")
        if phase_enc_dir is not None:
            phase_enc_dir = list(np.atleast_1d(phase_enc_dir))
            phase_enc_dir = [phase_enc_dir[0]] if is_all_element_same(phase_enc_dir) else phase_enc_dir
            num_slice_packs = len(phase_enc_dir)

        num_slices_each_pack = []
        sizes = {name: size for name, size in groups}
        if 'slice' in sizes:
            if num_slice_packs > 1:
                num_slices_each_pack = [int(sizes['slice'] / num_slice_packs) for _ in range(num_slice_packs)]
            else:
                num_slices_each_pack = [sizes['slice']]
        slice_distances_each_pack = [get_value(visu_pars, "VisuCoreFrameThickness") for _ in range(num_slice_packs)]
        return num_slice_packs, num_slices_each_pack, slice_distances_each_pack

    def _parse_6to360(self, visu_pars, groups):
        """Slice description for ParaVision 6 through 360.

        The packs are described directly by ``VisuCoreSlicePacks*``.
        """
        slice_packs_def = get_value(visu_pars, "VisuCoreSlicePacksDef")
        num_slice_packs = int(slice_packs_def[0][1]) if slice_packs_def is not None else 1
        slices_desc_in_pack = get_value(visu_pars, "VisuCoreSlicePacksSlices")
        slice_distance = get_value(visu_pars, "VisuCoreSlicePacksSliceDist")

        slice_distances_each_pack = []
        if any('slice' in name for name, _ in groups):
            if slices_desc_in_pack is not None:
                # VisuCoreSlicePacksSlices holds [first_slice_index, count] per
                # pack; read each pack's own count so unequal packs (e.g. a
                # [5, 3, 5] scout) are not flattened to the first pack's count.
                num_slices_each_pack = [slices_desc_in_pack[p][1] for p in range(num_slice_packs)]
            else:
                num_slices_each_pack = [1]
            if hasattr(slice_distance, '__len__'):
                slice_distances_each_pack.extend([slice_distance[0] for _ in range(num_slice_packs)])
            elif isinstance(slice_distance, (int, float)):
                slice_distances_each_pack.extend([slice_distance for _ in range(num_slice_packs)])
            else:
                self._warn("Not supported data type for Slice Distance")
        else:
            num_slices_each_pack = [1]
            slice_distances_each_pack = [get_value(visu_pars, "VisuCoreFrameThickness")]
        return num_slice_packs, num_slices_each_pack, slice_distances_each_pack

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
