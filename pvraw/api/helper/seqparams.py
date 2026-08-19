from __future__ import annotations

from typing import TYPE_CHECKING

from pvraw.lib.utils import get_value

from .base import BaseHelper

if TYPE_CHECKING:
    from ..analyzer import ScanInfoAnalyzer


class SeqParams(BaseHelper):
    """Per-scan acquisition parameters: timing, flip angle, sequence identity.

    The ``VisuAcq*`` values are read from ``visu_pars`` rather than the raw
    ``acqp``/``method`` equivalents because ParaVision normalises them there
    (and a derived reconstruction inherits them from the primary one, see
    ``ScanInfoAnalyzer._inherit_acq_params``). ``ACQ_scan_name`` has no Visu
    counterpart and comes from ``acqp``.

    Units are ParaVision's own and fixed: times in ms, bandwidth in Hz,
    flip angle in degrees.

    Dependencies:
        visu_pars
        acqp
    """
    def __init__(self, analobj: ScanInfoAnalyzer):
        super().__init__()
        visu_pars = analobj.visu_pars

        self.repetition_time = get_value(visu_pars, 'VisuAcqRepetitionTime')
        self.echo_time = get_value(visu_pars, 'VisuAcqEchoTime')
        self.flip_angle = get_value(visu_pars, 'VisuAcqFlipAngle')
        self.pixel_bandwidth = get_value(visu_pars, 'VisuAcqPixelBandwidth')
        self.sequence_name = get_value(visu_pars, 'VisuAcqSequenceName')
        self.scan_name = get_value(analobj.acqp, 'ACQ_scan_name')

    def get_info(self):
        return {
            'repetition_time': self.repetition_time,
            'echo_time': self.echo_time,
            'flip_angle': self.flip_angle,
            'pixel_bandwidth': self.pixel_bandwidth,
            'sequence_name': self.sequence_name,
            'scan_name': self.scan_name,
            'warns': self.warns
        }
