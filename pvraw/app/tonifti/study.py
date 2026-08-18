"""Docstring for public module D100, D200."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pvraw.api.data import Study

from .base import BaseMethods
from .scan import ScanToNifti

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Literal

    from nibabel.nifti1 import Nifti1Header


class StudyToNifti(Study, BaseMethods):
    """public class docstring."""
    def __init__(self, path:Path,
                 scale_mode: Literal['header', 'apply'] | None = None):
        super().__init__(path)
        self.set_scale_mode(scale_mode)
        self._cache = {}
    
    def get_scan(self, scan_id: int,
                 reco_id: int | None = None):
        if scan_id not in self._cache:
            self._cache[scan_id] = ScanToNifti(pvobj=self.get_pvscan(scan_id),
                                               reco_id=reco_id)
        return self._cache[scan_id]

    def get_scan_pvobj(self, scan_id: int):
        """The `brukerapi` Experiment behind one scan."""
        return self.get_pvscan(scan_id)


    def get_scan_analyzer(self, 
                          scan_id: int, 
                          reco_id: int | None = None):
        return self.get_scan(scan_id).get_scaninfo(reco_id=reco_id, 
                                                   get_analyzer=True)
    
    def get_affine(self, 
                   scan_id: int, 
                   reco_id: int | None = None, 
                   subj_type: str | None = None, 
                   subj_position: str | None = None):
        scanobj = self.get_scan(scan_id, reco_id)
        return super().get_affine(scanobj=scanobj, 
                                  reco_id=reco_id, 
                                  subj_type=subj_type, 
                                  subj_position=subj_position)
    
    def get_dataobj(self, scan_id: int, reco_id: int | None = None, 
                    scale_mode: Literal['header', 'apply'] | None = None):
        scale_mode = scale_mode or self.scale_mode
        scale_correction = not (not scale_mode or scale_mode == 'header')
        scanobj = self.get_scan(scan_id, reco_id)
        return super().get_dataobj(scanobj=scanobj, 
                                   reco_id=reco_id, 
                                   scale_correction=scale_correction)
    
    def get_data_dict(self, scan_id: int, 
                      reco_id: int | None = None):
        scanobj = self.get_scan(scan_id, reco_id)
        return super().get_data_dict(scanobj=scanobj,
                                     reco_id=reco_id)

    def get_affine_dict(self, 
                        scan_id: int, 
                        reco_id: int | None = None, 
                        subj_type: str | None = None, 
                        subj_position: str | None = None):
        scanobj = self.get_scan(scan_id=scan_id, 
                                reco_id=reco_id)
        return super().get_affine_dict(scanobj=scanobj,
                                       reco_id=reco_id,
                                       subj_type=subj_type,
                                       subj_position=subj_position)

    def update_nifti1header(self,
                            nifti1image: Nifti1Header,
                            scan_id: int, 
                            reco_id: int | None = None, 
                            scale_mode: Literal['header', 'apply'] | None = None):
        scale_mode = scale_mode or self.scale_mode
        scanobj = self.get_scan(scan_id=scan_id, 
                                reco_id=reco_id)
        return super().update_nifti1header(scanobj=scanobj,
                                           nifti1image=nifti1image, 
                                           scale_mode=scale_mode)

    def get_nifti1image(self, 
                        scan_id: int, 
                        reco_id: int | None = None, 
                        scale_mode: Literal['header', 'apply'] | None = None,
                        subj_type: str | None = None, 
                        subj_position: str | None = None):
        scale_mode = scale_mode or self.scale_mode
        scanobj = self.get_scan(scan_id=scan_id,
                                reco_id=reco_id)
        return super().get_nifti1image(scanobj=scanobj,
                                       reco_id=reco_id,
                                       scale_mode=scale_mode,
                                       subj_type=subj_type, 
                                       subj_position=subj_position)
        
    @property
    def info(self):
        # scan cycle
        header = super().info['header']
        scans = super().info['scans']
        title = header['sw_version']
        print(title)
        print('-' * len(title))
        print('date: {date}')
        for key, value in header.items():
            if key not in ['date', 'sw_version']:
                print(f'{key}:\t{value}')
        print('\n[ScanID]\tMethod::Protocol')
        max_size = len(str(max(scans.keys())))
        
        for scan_id, value in scans.items():
            print(f"[{str(scan_id).zfill(max_size)}]\t{value['method']}::{value['protocol']}")
            if value.get('recos'):
                print('\tRECO:', list(value['recos'].keys()))