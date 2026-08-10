"""
dependency:
    bids, plugin
"""
from brkraw_legacy import config
from brkraw_legacy.app.tonifti.plugin import ToNiftiPlugin
from brkraw_legacy.app.tonifti.study import ScanToNifti, StudyToNifti

tonifti_config = config.config['app']['tonifti']
# tonifti_presets = config.get_fetcher('preset')

__all__ = ['ScanToNifti', 'StudyToNifti', 'ToNiftiPlugin']
