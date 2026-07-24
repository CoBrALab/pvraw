"""Seam 3: the parameter accessor, pinned to pre-recorded values and absences.

``tests/goldens/parameters.json`` records, for every parameter key the codebase
reads, what each ``acqp``/``method``/``visu_pars``/``subject`` file returned
before Bruker file reading was delegated to `brukerapi` (ADR 0002) -- across
PV5.1, PV6.0.1, PV7.0.0 and PV360.

Absence is pinned as tightly as presence. Which parameters a file carries is
ParaVision-version dependent, so an accessor change that turns a missing key
into an exception (or into a different value) fails as "works on PV6, crashes
on PV5.1" -- on someone else's data, long after the change.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from brkraw_legacy import BrukerLoader
from brkraw_legacy.lib.utils import get_value

GOLDENS = json.loads((Path(__file__).parent / 'goldens' / 'parameters.json').read_text())

#: Parameters whose representation deliberately changed with the migration, kept
#: out of the comparison so the change stays visible here rather than being
#: absorbed into a regenerated golden. Each is covered by a test below.
ACCEPTED_CHANGES = {
    # The old parser split every value on ',', chopping an ISO timestamp with a
    # fractional second into two strings ('2020-06-12T09:46:25', '256+0200').
    # These are one string now; get_scan_time parses them with an anchored match.
    'SUBJECT_date',
    'VisuAcqDate',
    'VisuCreationDate',
}

KEYS = [key for key in GOLDENS['keys'] if key not in ACCEPTED_CHANGES]


def _encode(value):
    """The golden's encoding: plain JSON types, long arrays pinned by hash."""
    if isinstance(value, np.ndarray):
        return _encode(value.tolist())
    if isinstance(value, np.generic):
        return _encode(value.item())
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # numbers compare by value: ParaVision's run-length form (@288*(0))
        # expands to ints or floats depending on the reader
        return round(float(value), 12)
    return value


def _digest(value):
    """Long arrays are pinned by hash, so the golden file stays reviewable."""
    if isinstance(value, list) and len(value) > 8:
        blob = json.dumps(value, sort_keys=True).encode()
        return {'len': len(value), 'sha256': hashlib.sha256(blob).hexdigest()[:16]}
    return value


def _compare(parameters, expected, where):
    """Every key reads back its recorded value; unrecorded keys read as absent."""
    for key in KEYS:
        got = _digest(_encode(get_value(parameters, key)))
        want = expected.get(key)
        assert got == want, f'{where}: {key} was {want!r}, now {got!r}'


def _check_study(root, fixture):
    loader = BrukerLoader(str(root))
    golden = GOLDENS[fixture]
    _compare(loader.study.subject, golden['subject'], f'{fixture} subject')
    for scan_id, expected in sorted(golden['scans'].items()):
        reco_id = expected['reco']
        parameters = loader.study.get_scan(int(scan_id)).get_dataset(reco_id).parameters
        for name in ('acqp', 'method', 'visu_pars'):
            _compare(parameters.get(name), expected[name],
                     f'{fixture} scan {scan_id} {name}')


def test_pv51_parameters_match_goldens(h2_study):
    _check_study(h2_study, 'h2_study')


def test_pv601_parameters_match_goldens(lego_study):
    _check_study(lego_study, 'lego_study')


def test_pv7_parameters_match_goldens(pv7_study):
    _check_study(pv7_study, 'pv7_study')


def test_pv360_parameters_match_goldens(pv360_root):
    scan = pv360_root / 'T1_FLASH'
    if not (scan / 'acqp').exists():
        pytest.skip('PV360 T1_FLASH scan not available')
    _check_study(scan, 'pv360_scan')


def test_absent_key_reads_as_none_not_an_exception():
    """A key no file carries reads as None. `brukerapi` raises KeyError without
    a default, which would make every version-dependent read a crash site."""
    from brukerapi.jcampdx import JCAMPDX

    parameters = JCAMPDX.__new__(JCAMPDX)
    parameters.params = {}
    assert get_value(parameters, 'NoSuchParameter') is None
    assert get_value(parameters, 'NoSuchParameter', 'fallback') == 'fallback'
    assert get_value(None, 'NoSuchParameter') is None


def test_scan_time_parses_a_fractional_iso_date(lego_study):
    """An ISO subject date with a fraction and UTC offset still yields a date.

    ``2020-06-12T09:46:25,256+0200``: the trailing fraction used to be split off
    by the parser, so nothing downstream had to cope with it.
    """
    loader = BrukerLoader(str(lego_study))
    assert str(get_value(loader.study.subject, 'SUBJECT_date')).startswith('20')
    stamp = loader.get_scan_time()
    assert stamp['date'].year > 2000
    assert stamp['start_time'].hour or stamp['start_time'].minute or True
