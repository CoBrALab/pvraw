from __future__ import annotations

from typing import TYPE_CHECKING

from pvraw.lib import tabular
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
        self.inversion_time = get_value(visu_pars, 'VisuAcqInversionTime')
        self.flip_angle = get_value(visu_pars, 'VisuAcqFlipAngle')
        self.pixel_bandwidth = get_value(visu_pars, 'VisuAcqPixelBandwidth')
        self.num_averages = get_value(visu_pars, 'VisuAcqNumberOfAverages')
        self.echo_train_length = get_value(visu_pars, 'VisuAcqEchoTrainLength')
        self.imaging_frequency = get_value(visu_pars, 'VisuAcqImagingFrequency')
        self.sequence_name = get_value(visu_pars, 'VisuAcqSequenceName')
        # The acquisition start, as BIDS spells a datetime (see tabular.acq_time).
        self.acq_date = tabular.acq_time(visu_pars) if visu_pars else None
        self.scan_name = get_value(analobj.acqp, 'ACQ_scan_name')
        # NR has no Visu counterpart: the repetitions become FG_MOVIE/FG_CYCLE frames.
        self.num_repetitions = get_value(analobj.method, 'PVM_NRepetitions')

    def get_info(self):
        return {
            'repetition_time': self.repetition_time,
            'echo_time': self.echo_time,
            'inversion_time': self.inversion_time,
            'flip_angle': self.flip_angle,
            'pixel_bandwidth': self.pixel_bandwidth,
            'num_averages': self.num_averages,
            'num_repetitions': self.num_repetitions,
            'echo_train_length': self.echo_train_length,
            'imaging_frequency': self.imaging_frequency,
            'sequence_name': self.sequence_name,
            'acq_date': self.acq_date,
            'scan_name': self.scan_name,
            'warns': self.warns
        }
