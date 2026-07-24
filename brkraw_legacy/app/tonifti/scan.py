from __future__ import annotations
from pathlib import Path
from brukerapi.exceptions import NotExperimentFolder, NotProcessingFolder
from brukerapi.folders import Experiment, Processing
from brkraw_legacy.api.data import Scan
from brkraw_legacy.api.data.study import UNLOADED
from brkraw_legacy.lib.errors import FileNotValidError
from .base import BaseMethods
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Union, Optional, Literal
    from brkraw_legacy.api import PlugInSnippet
    from nibabel.nifti1 import Nifti1Image


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
                 path: Optional[Path] = None,
                 scale_mode: Optional[Literal['header', 'apply']] = None,
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

    def get_affine(self, reco_id: Optional[int] = None,
                   subj_type: Optional[str] = None,
                   subj_position: Optional[str] = None):
        return super().get_affine(scanobj = self,
                                  reco_id = reco_id,
                                  subj_type = subj_type,
                                  subj_position = subj_position)

    def get_dataobj(self, reco_id: Optional[int] = None,
                    scale_mode: Optional[Literal['header', 'apply']] = None):
        scale_mode = scale_mode or self.scale_mode
        scale_correction = False if not scale_mode or scale_mode == 'header' else True
        if reco_id:
            self.set_scaninfo(reco_id)
        return super().get_dataobj(scanobj = self,
                                   reco_id = reco_id,
                                   scale_correction = scale_correction)

    def get_data_dict(self, reco_id: Optional[int] = None):
        if reco_id:
            self.set_scaninfo(reco_id)
        return super().get_data_dict(scanobj=self, reco_id=reco_id)

    def get_affine_dict(self, reco_id: Optional[int] = None,
                        subj_type: Optional[str] = None,
                        subj_position: Optional[str] = None):
        if reco_id:
            self.set_scaninfo(reco_id)
        return super().get_affine_dict(scanobj = self,
                                       reco_id = reco_id,
                                       subj_type = subj_type,
                                       subj_position = subj_position)

    def update_nifti1header(self,
                            nifti1obj: 'Nifti1Image',
                            reco_id: Optional[int] = None,
                            scale_mode: Optional[Literal['header', 'apply']] = None):
        scale_mode = scale_mode or self.scale_mode
        return super().update_nifti1header(self, nifti1obj, reco_id, scale_mode)

    def get_nifti1image(self,
                        reco_id: Optional[int] = None,
                        scale_mode: Optional[Literal['header', 'apply']] = None,
                        subj_type: Optional[str] = None,
                        subj_position: Optional[str] = None,
                        plugin: Optional[Union['PlugInSnippet', str]] = None,
                        plugin_kws: dict = None):
        scale_mode = scale_mode or self.scale_mode
        return super().get_nifti1image(self,
                                       reco_id,
                                       scale_mode,
                                       subj_type,
                                       subj_position,
                                       plugin,
                                       plugin_kws)
