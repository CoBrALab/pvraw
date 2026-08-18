"""ParaVision-version reporting (lib.loader).

Pure-unit (offline). ``info``'s title line takes the version from `brukerapi`'s
``pv_version`` rather than reading ``VisuCreatorVersion`` directly, because the
raw parameter is not always a bare version: PV5.1 writes ``5.1;5.1`` on 34 of
the reconstructions in ``resources/testdata``, and where it is numeric rather
than quoted it parses as a float (``5.1``) instead of a string.

``pv_version`` is a recipe-derived property, and those raise ``AttributeError``
rather than defaulting when their conditions do not match, so the direct read
stays as the fallback.
"""
from pvraw.lib.loader import BrukerLoader


class _Params(dict):
    def get_parameter(self, key):
        return _Value(self[key])


class _Value:
    def __init__(self, value):
        self.value = value
        self.val_str = str(value)
        self.nested = value


class _Dataset:
    """Stands in for `brukerapi`'s ``Dataset.get``: a declared property that did
    not resolve reads as the default rather than raising (0.4.3, #178)."""
    def __init__(self, pv_version=None):
        self._pv_version = pv_version

    def get(self, name, default=None):
        if name != 'pv_version':
            raise AttributeError(f"'Dataset' object has no attribute '{name}'")
        return self._pv_version if self._pv_version is not None else default


def test_uses_upstream_version_over_the_raw_parameter():
    """PV5.1 writes VisuCreatorVersion as `5.1;5.1`; pv_version normalises it."""
    assert BrukerLoader._pv_version(
        _Dataset('5.1'), _Params({'VisuCreatorVersion': '5.1;5.1'})) == '5.1'


def test_falls_back_to_the_parameter_when_the_property_is_absent():
    """A recipe property that does not resolve raises instead of returning
    None, so the direct read has to remain reachable."""
    assert BrukerLoader._pv_version(
        _Dataset(), _Params({'VisuCreatorVersion': '6.0.1'})) == '6.0.1'


def test_missing_everywhere_is_not_an_error():
    """`info` must still print a header for a study with neither."""
    assert BrukerLoader._pv_version(_Dataset(), _Params({})) is None
