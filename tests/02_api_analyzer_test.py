"""Unit tests for ScanInfoAnalyzer's parameter binding.

Pure-unit (offline): a derived reconstruction must inherit the acquisition-level
parameters it omits from the scan's primary reconstruction, and nothing else.
"""
from types import SimpleNamespace

from brkraw_legacy.api.analyzer.scaninfo import ScanInfoAnalyzer


class _Params(dict):
    """A JCAMPDX stand-in: the accessors ScanInfoAnalyzer uses, over a dict."""
    def get_parameter(self, key):
        return self[key]

    def set_parameter(self, key, value):
        self[key] = value


def _analyzer(visu_pars, primary=None):
    """An analyzer bound to `visu_pars`, with `primary` as the first reco's."""
    analyzer = ScanInfoAnalyzer.__new__(ScanInfoAnalyzer)
    analyzer.dataset = SimpleNamespace(path=None)
    analyzer.acqp = analyzer.method = None
    analyzer.visu_pars = visu_pars
    analyzer._primary_visu_pars = lambda: primary
    return analyzer


def test_derived_reco_inherits_only_acquisition_params():
    """A derived reconstruction (e.g. a computed T2/ADC map) inherits the
    acquisition-level VisuAcq* parameters it omits from the primary reco, while
    keeping its own reconstruction geometry."""
    primary = _Params({'VisuAcqGradEncoding': ['read_enc', 'phase_enc'],
                       'VisuAcqImagePhaseEncDir': ['col_dir'],
                       'VisuCoreSize': [256, 256]})
    derived = _Params({'VisuCoreSize': [128, 128]})   # no VisuAcq*; its own matrix

    _analyzer(derived, primary)._inherit_acq_params()

    assert derived['VisuAcqGradEncoding'] == ['read_enc', 'phase_enc']  # inherited
    assert derived['VisuAcqImagePhaseEncDir'] == ['col_dir']            # inherited
    assert derived['VisuCoreSize'] == [128, 128]                        # kept, not primary's


def test_primary_reco_params_untouched():
    """The primary reconstruction has nothing to inherit and is unchanged."""
    primary = _Params({'VisuAcqGradEncoding': ['read_enc'], 'VisuCoreSize': [256, 256]})
    _analyzer(primary, None)._inherit_acq_params()
    assert set(primary) == {'VisuAcqGradEncoding', 'VisuCoreSize'}
