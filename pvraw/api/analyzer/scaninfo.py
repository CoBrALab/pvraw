"""Scan information analysis module.

Turns the parameter files of one reconstruction into the derived values the
geometry, NIfTI-header and BIDS layers consume. The parameter files themselves
come from a `brukerapi` ``Dataset`` (ADR 0002); what is computed here is
pvraw's own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pvraw.api import helper

from .base import BaseAnalyzer

if TYPE_CHECKING:
    from brukerapi.dataset import Dataset


class ScanInfoAnalyzer(BaseAnalyzer):
    """Parses one reconstruction's parameters into human-readable information.

    Args:
        dataset: The `brukerapi` Dataset for the reconstruction, carrying its
            ``visu_pars`` plus the scan's ``acqp`` and ``method``.
        primary_visu_pars: The scan's first reconstruction's ``visu_pars``,
            which a derived reconstruction inherits acquisition parameters from.
            None when this *is* the first reconstruction.
        debug (bool): Stop after the parameter files are bound, before the
            derived values are computed.

    Attributes:
        acqp, method, visu_pars: The parameter files, as `brukerapi` JCAMPDX
            objects (``get_value(key, default)`` reads them).
        dataset: The Dataset the values were derived from.
    """
    def __init__(self, dataset: Dataset, primary_visu_pars=None, debug: bool = False):
        self._primary_visu_pars = primary_visu_pars
        self._set_pars(dataset)
        if not debug:
            self.info_protocol = helper.Protocol(self).get_info()
            if self.visu_pars:
                self._parse_info()

    def _set_pars(self, dataset: Dataset):
        """Bind the parameter files of `dataset` for the helpers to read."""
        self.dataset = dataset
        parameters = dataset.parameters if dataset is not None else {}
        for name in ('acqp', 'method', 'visu_pars'):
            setattr(self, name, parameters.get(name))
        self._inherit_acq_params()

    def _inherit_acq_params(self):
        """Complete a derived reconstruction's parameters with acquisition-level
        Visu parameters it omits.

        A scan has one acquisition but several reconstructions. Acquisition
        parameters (``VisuAcq*``) describe that shared acquisition, not a
        reconstruction's geometry, so an extra reco can leave them out (e.g.
        ``VisuAcqGradEncoding`` / ``VisuAcqImagePhaseEncDir`` on a computed
        T2/ADC map). Source only those from the primary (first) reconstruction,
        where they always live; reconstruction-specific parameters (``VisuCore*``,
        ``VisuFG*``, ...) are left to the reco itself so its own geometry is used.
        """
        primary = self._primary_visu_pars
        if self.visu_pars is None or primary is None or primary is self.visu_pars:
            return
        for key in primary:
            if key.startswith('VisuAcq') and key not in self.visu_pars:
                self.visu_pars.set_parameter(key, primary.get_parameter(key))

    def _parse_info(self):
        """Derive the values the geometry, header and BIDS layers consume."""
        self.info_dataarray = helper.DataArray(self).get_info()
        self.info_seqparams = helper.SeqParams(self).get_info()
        self.info_image = helper.Image(self).get_info()
        self.info_slicepack = helper.SlicePack(self).get_info()
        self.info_cycle = helper.Cycle(self).get_info()
        self.info_diffusion = helper.Diffusion(self).get_info()
        if self.info_image['dim'] > 1:
            self.info_orientation = helper.Orientation(self).get_info()

    def __dir__(self):
        """The informational properties this analyzer derived."""
        return [attr for attr in self.__dict__ if 'info_' in attr]

    def get(self, key):
        """One informational property by name, or None if it was not derived."""
        return getattr(self, key) if key in self.__dir__() else None
