from typing import Literal

from .plugin import ToNiftiPlugin
from .scan import ScanToNifti
from .study import StudyToNifti

ToNiftiPluginType = type[ToNiftiPlugin]

ScanToNiftiType = type[ScanToNifti]

StudyToNiftiType = type[StudyToNifti]

ToNiftiObject = type[ToNiftiPlugin | ScanToNifti | StudyToNifti]

ScaleMode = type[Literal['header', 'apply'] | None]

__all__ = ['ScanToNifti', 'StudyToNifti', 'ToNiftiPlugin']

