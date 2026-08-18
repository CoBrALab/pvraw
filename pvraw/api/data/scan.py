"""Scan-level container: one acquisition and its reconstructions.

A Scan wraps a `brukerapi` ``Experiment``; a Reco is one of its ``Processing``
folders (see ``CONTEXT.md``). Every read of a reconstruction -- parameters,
shape, dtype, scaling factors, the image itself -- goes through a `brukerapi`
``Dataset`` built here (ADR 0002).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from brukerapi.dataset import LOAD_STAGES, Dataset

from pvraw.api.analyzer import AffineAnalyzer, BaseAnalyzer, ScanInfoAnalyzer

if TYPE_CHECKING:

    from brukerapi.folders import Processing


class ScanInfo(BaseAnalyzer):
    """Analysed scan properties, plus the warnings raised while deriving them."""
    def __init__(self) -> None:
        self.warns: list[str] = []

    @property
    def num_warns(self) -> int:
        return len(self.warns)


class Scan(BaseAnalyzer):
    """One scan of a study, addressed by ``reco_id`` for its reconstructions.

    Attributes:
        pvobj: The `brukerapi` Experiment this scan reads through.
        reco_id (Optional[int]): The reconstruction bound by default.
    """
    def __init__(self, pvobj, reco_id: int | None = None,
                 debug: bool = False) -> None:
        self.pvobj = pvobj
        self.is_debug = debug
        self.reco_id = reco_id or (self.avail[0] if self.avail else None)
        #: Parameter-only datasets are cached; data-carrying ones never are, so
        #: sweeping a study does not accumulate whole image arrays.
        self._properties: dict = {}
        self._info = None

    @property
    def avail(self) -> list[int]:
        """Available ``reco_id``s, ascending.

        A reconstruction is addressable when its folder holds both the
        visualisation parameters (which make it a ``Processing``) and a
        ``2dseq``; PROCNO folders are numbered.
        """
        return sorted(int(proc.path.name)
                      for proc in self._recos()
                      if proc.path.name.isdigit() and (proc.path / '2dseq').exists())

    def _recos(self) -> list:
        # Normally the PROCNOs sit under the scan's `pdata`. The list includes
        # the scan folder itself when that is a bare reconstruction directory --
        # or when a scan carries a stray `visu_pars` at its root -- and `avail`
        # keeps only the folders that actually hold a 2dseq.
        return self.pvobj.get_processing_list()

    def get_dataset(self, reco_id: int | None = None, *, with_data: bool = False):
        """The `brukerapi` Dataset for one reconstruction.

        Without `with_data` the 2dseq binary is not read: shape, dtype, scaling
        factors and named axes are all derived properties, so the affine, the
        NIfTI header and the BIDS metadata never touch the image data.

        Scaling is left off. The intensity slope and offset stay available as
        ``dataset.slope``/``dataset.offset`` and are applied where the NIfTI is
        assembled, which can put a scalar pair in ``scl_slope``/``scl_inter``
        instead of widening every image to float.
        """
        reco_id = reco_id or self.reco_id
        if not with_data and reco_id in self._properties:
            return self._properties[reco_id]
        proc = self._get_reco(reco_id)
        dataset = Dataset(proc.path / '2dseq',
                          scale=False,
                          combine_complex=False,
                          parameter_files=['method', 'acqp'],
                          load=LOAD_STAGES['all'] if with_data else LOAD_STAGES['properties'])
        if not with_data:
            self._properties[reco_id] = dataset
        return dataset

    def _get_reco(self, reco_id: int | None) -> Processing:
        for proc in self._recos():
            if proc.path.name.isdigit() and int(proc.path.name) == reco_id:
                return proc
        raise KeyError(f'RecoID:[{reco_id}] not found in ScanID:[{self.pvobj.path.name}]')

    def get_visu_pars(self, reco_id: int | None = None):
        """The ``visu_pars`` of one reconstruction, as a `brukerapi` JCAMPDX."""
        return self.get_dataset(reco_id).parameters['visu_pars']

    @property
    def info(self) -> ScanInfo:
        """Analysed properties of the bound reconstruction.

        Derived on first use rather than in the constructor, so a scan that
        cannot be analysed -- spectroscopy, an empty reconstruction -- can
        still be constructed and rejected with a clear message.
        """
        if self._info is None:
            self._info = self.get_scaninfo(self.reco_id)
        return self._info

    def set_scaninfo(self, reco_id: int | None = None) -> None:
        """Rebind ``info`` to `reco_id`, leaving the scan's default unchanged."""
        self._info = self.get_scaninfo(reco_id or self.reco_id)

    def get_scaninfo(self, reco_id: int | None = None,
                     get_analyzer: bool = False):
        """Analysed properties of one reconstruction.

        With `get_analyzer` the analyzer itself is returned, carrying the raw
        parameter files alongside the derived values.
        """
        analysed = ScanInfoAnalyzer(self.get_dataset(reco_id),
                                    primary_visu_pars=self._primary_visu_pars(reco_id),
                                    debug=self.is_debug)
        if get_analyzer:
            return analysed
        infoobj = ScanInfo()
        for attr_name in dir(analysed):
            if 'info_' in attr_name:
                attr_vals = getattr(analysed, attr_name)
                if warns := attr_vals.pop('warns', None):
                    infoobj.warns.extend(warns)
                setattr(infoobj, attr_name.replace('info_', ''), attr_vals)
        return infoobj

    def _primary_visu_pars(self, reco_id: int | None = None):
        """The first reconstruction's ``visu_pars``, or None if `reco_id` is it.

        A derived reconstruction omits the acquisition-level parameters that
        describe the shared acquisition; the first reconstruction always has
        them (see ScanInfoAnalyzer._inherit_acq_params).
        """
        recos = self.avail
        reco_id = reco_id or self.reco_id
        if not recos or reco_id == recos[0]:
            return None
        return self.get_dataset(recos[0]).parameters.get('visu_pars')

    def get_affine_analyzer(self, reco_id: int | None = None) -> AffineAnalyzer:
        info = self.get_scaninfo(reco_id) if reco_id else self.info
        return AffineAnalyzer(info, self.get_dataset(reco_id))

    @property
    def about_scan(self) -> dict:
        return self.info.to_dict()

    @property
    def about_affine(self) -> dict:
        return self.get_affine_analyzer().to_dict()
