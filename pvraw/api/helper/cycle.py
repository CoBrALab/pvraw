from __future__ import annotations

from typing import TYPE_CHECKING

from pvraw.lib.utils import get_value

from .base import BaseHelper, frame_groups

if TYPE_CHECKING:
    from ..analyzer import ScanInfoAnalyzer


class Cycle(BaseHelper):
    """Repetition structure of a reconstruction.

    Dependencies:
        dataset
        visu_pars
    """
    def __init__(self, analobj: ScanInfoAnalyzer):
        super().__init__()
        scan_time = get_value(analobj.visu_pars, "VisuAcqScanTime") or 0
        cycles = [size for name, size in frame_groups(analobj.dataset) if 'cycle' in name]
        self.num_cycles = cycles.pop() if cycles else 1
        self.time_step = (scan_time / self.num_cycles)
        # Total acquisition time (ms). The NIfTI header divides it by the volume
        # count to get the per-volume time step on pixdim[4] -- the BIDS func
        # RepetitionTime (wall-clock time between volumes), which for multi-shot /
        # segmented or averaged EPI exceeds the sequence VisuAcqRepetitionTime.
        self.scan_time = scan_time

    def get_info(self):
        return {
            "num_cycles": self.num_cycles,
            "time_step": self.time_step,
            "scan_time": self.scan_time,
            "unit": 'msec',
            'warns': self.warns
            }
