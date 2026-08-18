"""This module create header
currently not functioning as expected, need to work more
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import numpy as np
from nibabel.nifti1 import Nifti1Image

if TYPE_CHECKING:
    from typing import Literal

    from pvraw.api.data import ScanInfo


class Header:
    info: ScanInfo
    scale_mode: int
    nifti1image: Nifti1Image
    
    def __init__(self, 
                 scaninfo: ScanInfo,
                 nifti1image: Nifti1Image,
                 scale_mode: Literal['header', 'apply'] | None = None):
        self.info = scaninfo
        self.scale_mode = 1 if scale_mode == 'header' else 0
        self.nifti1image = nifti1image
        self.nifti1image.header.default_x_flip = False
        self._set_scale_params()
        self._set_sliceorder()
        self._set_slice_extent()
        self._set_time_step()
        self._set_sform_qform()
        self._set_cal_and_descrip()
        
    def _set_sliceorder(self):
        # Bruker PVM_ObjOrderScheme -> NIfTI slice_code. Enum spellings are taken
        # verbatim from the ParaVision installs: PV5.1 emits Sequential /
        # Reverse_sequential / Interlaced, PV6.0.1 emits Sequential /
        # Reverse_interlaced / Interlaced. Interlaced maps to NIFTI_SLICE_ALT_INC
        # (even-first); the scheme name alone cannot distinguish ALT_INC from
        # ALT_INC2 (odd-first), so slice-timing consumers should still cross-check
        # the acquisition order. Anything unmapped (e.g. User_defined_slice_scheme)
        # stays 0 = NIFTI_SLICE_UNKNOWN.
        slice_code = {
            'Sequential':         1,   # NIFTI_SLICE_SEQ_INC
            'Reverse_sequential': 2,   # NIFTI_SLICE_SEQ_DEC
            'Interlaced':         3,   # NIFTI_SLICE_ALT_INC
            'Reverse_interlaced': 4,   # NIFTI_SLICE_ALT_DEC
        }.get(self.info.slicepack['slice_order_scheme'], 0)

        if slice_code == 0:
            warnings.warn(
                "Failed to identify compatible 'slice_code'. "
                "Please use this header information with care in case slice timing correction is needed."
            )
        self.nifti1image.header['slice_code'] = slice_code

    def _set_slice_extent(self):
        # A slice_code is inert without the slice axis and the slice range it
        # applies to. The assembly pipeline always places the slice axis third
        # (k), spanning the whole volume, so record that. The freq/phase entries
        # of dim_info are left unset here: mapping them onto the reoriented image
        # axes belongs with PhaseEncodingDirection, not this field.
        if self.nifti1image.ndim >= 3:
            self.nifti1image.header.set_dim_info(slice=2)
            self.nifti1image.header['slice_start'] = 0
            self.nifti1image.header['slice_end'] = self.nifti1image.shape[2] - 1

    def _set_time_step(self):
        # Bruker voxel geometry is always in mm; label the spatial units
        # unconditionally so they are not left NIFTI_UNITS_UNKNOWN. A 4D series
        # additionally carries a per-volume time step (seconds) on pixdim[4].
        #
        # The step is the wall-clock time between volumes = VisuAcqScanTime /
        # number-of-volumes. For func this is exactly the BIDS RepetitionTime
        # (which the converter derives the same way), so the NIfTI header and the
        # JSON sidecar agree (avoids BIDS REPETITION_TIME_MISMATCH). It also
        # correctly exceeds the sequence VisuAcqRepetitionTime for multi-shot /
        # segmented or averaged acquisitions, where one volume spans several TRs.
        # (The old cycle time_step = ScanTime/num_cycles is a per-cycle interval
        # that disagrees whenever a cycle spans more than one volume, and it only
        # ran when a cycle frame group was detected.)
        if self.nifti1image.ndim >= 4:
            scan_time = self.info.cycle.get('scan_time')
            num_volumes = self.nifti1image.shape[3]
            if isinstance(scan_time, (int, float, np.integer, np.floating)) \
                    and not isinstance(scan_time, bool) and scan_time > 0 and num_volumes:
                time_step = (scan_time / num_volumes) / 1000
                self.nifti1image.header['pixdim'][4] = time_step
                num_slices = self.info.slicepack['num_slices_each_pack'][0]
                if num_slices:
                    self.nifti1image.header['slice_duration'] = time_step / num_slices
            self.nifti1image.header.set_xyzt_units('mm', 'sec')
        else:
            self.nifti1image.header.set_xyzt_units('mm')
            
    def _set_sform_qform(self):
        # A Nifti1Image built from an affine defaults to sform_code=2 (ALIGNED)
        # with the qform left unset (code 0). This data comes straight off the
        # scanner, so tag both forms with the same affine and code 1
        # (NIFTI_XFORM_SCANNER_ANAT): sform-first tools are unaffected, and tools
        # that honor only the qform now get the correct orientation too.
        affine = self.nifti1image.affine
        self.nifti1image.header.set_qform(affine, code=1)
        self.nifti1image.header.set_sform(affine, code=1)

    def _set_cal_and_descrip(self):
        # cal_min/cal_max give viewers a default display window; NIfTI expects
        # them in true (post-scaling) units. With scalar scl_slope/scl_inter in
        # the header the stored data is raw, so scale the min/max to true units
        # (a negative slope flips the ordering). When scaling is baked into the
        # data ('apply') or is per-frame, the array already holds true values.
        self.nifti1image.header['descrip'] = b'pvraw'
        data = np.asarray(self.nifti1image.dataobj)
        if not data.size:
            return
        lo, hi = float(np.nanmin(data)), float(np.nanmax(data))
        if self.scale_mode:
            slope = self.info.dataarray['slope']
            inter = self.info.dataarray['offset']
            if not (np.ndim(slope) or np.ndim(inter)):
                lo, hi = slope * lo + inter, slope * hi + inter
                lo, hi = min(lo, hi), max(lo, hi)
        self.nifti1image.header['cal_min'] = lo
        self.nifti1image.header['cal_max'] = hi

    def _set_scale_params(self):
        if self.scale_mode:
            slope = self.info.dataarray['slope']
            inter = self.info.dataarray['offset']
            if np.ndim(slope) or np.ndim(inter):
                # Per-volume slope/offset (e.g. fMRI) cannot be stored in NIfTI's
                # scalar scl_slope/scl_inter; leave them at the header default
                # rather than crashing. Baking per-volume scaling into the data
                # is a separate concern (the BrukerLoader path does this).
                warnings.warn(
                    "Per-volume scale factors are not representable in the NIfTI "
                    "header; scl_slope/scl_inter left at default.", UserWarning)
            else:
                self.nifti1image.header.set_slope_inter(slope=slope, inter=inter)
        self._update_dtype()

    def _update_dtype(self):
        self.nifti1image.header.set_data_dtype(self.nifti1image.dataobj.dtype)

    def get(self):
        return self.nifti1image