from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from brukerapi.exceptions import NotExperimentFolder, NotProcessingFolder
from brukerapi.folders import Experiment, Processing

from brkraw_legacy.api.data import Scan
from brkraw_legacy.api.data.study import UNLOADED
from brkraw_legacy.lib.errors import FileNotValidError

from .base import BaseMethods

if TYPE_CHECKING:
    from typing import Literal

    from nibabel.nifti1 import Nifti1Image

    from brkraw_legacy.api import PlugInSnippet


def _open_scan(path: Path):
    """Open an individually exported scan or reconstruction directory.

    Both shapes are what a real ParaVision export looks like: a scan directory
    holds ``acqp`` and its PROCNOs, a reconstruction directory holds
    ``visu_pars`` and its ``2dseq``.
    """
    try:
        return Experiment(path, dataset_state=UNLOADED)
    except NotExperimentFolder:
        pass
    try:
        return Processing(path, dataset_state=UNLOADED)
    except NotProcessingFolder:
        raise FileNotValidError(str(path), 'Bruker scan or reconstruction') from None


class ScanToNifti(Scan, BaseMethods):
    def __init__(self,
                 path: Path | None = None,
                 scale_mode: Literal['header', 'apply'] | None = None,
                 **kwargs):
        """A scan, converted to NIfTI.

        Args:
            path: a scan directory (``acqp`` + ``pdata``) or a single
                reconstruction directory (``visu_pars`` + ``2dseq``).
            scale_mode: 'header' leaves the intensity slope/offset in
                scl_slope/scl_inter, 'apply' bakes it into the data.
        """
        self.scale_mode = scale_mode
        if path is not None:
            kwargs['pvobj'] = _open_scan(Path(path).absolute())
        super().__init__(**kwargs)

    def get_affine(self, reco_id: int | None = None,
                   subj_type: str | None = None,
                   subj_position: str | None = None):
        return super().get_affine(scanobj = self,
                                  reco_id = reco_id,
                                  subj_type = subj_type,
                                  subj_position = subj_position)

    def get_dataobj(self, reco_id: int | None = None,
                    scale_mode: Literal['header', 'apply'] | None = None):
        scale_mode = scale_mode or self.scale_mode
        scale_correction = not (not scale_mode or scale_mode == 'header')
        if reco_id:
            self.set_scaninfo(reco_id)
        return super().get_dataobj(scanobj = self,
                                   reco_id = reco_id,
                                   scale_correction = scale_correction)

    def get_data_dict(self, reco_id: int | None = None):
        if reco_id:
            self.set_scaninfo(reco_id)
        return super().get_data_dict(scanobj=self, reco_id=reco_id)

    def get_affine_dict(self, reco_id: int | None = None,
                        subj_type: str | None = None,
                        subj_position: str | None = None):
        if reco_id:
            self.set_scaninfo(reco_id)
        return super().get_affine_dict(scanobj = self,
                                       reco_id = reco_id,
                                       subj_type = subj_type,
                                       subj_position = subj_position)

    def update_nifti1header(self,
                            nifti1obj: Nifti1Image,
                            reco_id: int | None = None,
                            scale_mode: Literal['header', 'apply'] | None = None):
        scale_mode = scale_mode or self.scale_mode
        return super().update_nifti1header(self, nifti1obj, reco_id, scale_mode)

    def get_nifti1image(self,
                        reco_id: int | None = None,
                        scale_mode: Literal['header', 'apply'] | None = None,
                        subj_type: str | None = None,
                        subj_position: str | None = None,
                        plugin: PlugInSnippet | str | None = None,
                        plugin_kws: dict | None = None):
        scale_mode = scale_mode or self.scale_mode
        return super().get_nifti1image(self,
                                       reco_id,
                                       scale_mode,
                                       subj_type,
                                       subj_position,
                                       plugin,
                                       plugin_kws)
