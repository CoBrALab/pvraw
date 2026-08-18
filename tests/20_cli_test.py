"""Tests for the command-line interface (scripts/pvraw.py).

The id-list parsing is pure-unit (offline). The selection test runs the real
``tonii`` against a public sample study, so it carries the ``data`` marker
through its fixture.
"""
import argparse
import subprocess

import pytest

from pvraw import BrukerLoader
from pvraw.scripts.pvraw import id_list


@pytest.mark.parametrize(('text', 'expected'), [
    ('3', [3]),
    ('3,4,7', [3, 4, 7]),
    ('3, 4', [3, 4]),          # a shell-quoted list with spaces
    ('3,4,', [3, 4]),          # trailing separator
])
def test_id_list_accepts_one_id_or_several(text, expected):
    assert id_list(text) == expected


@pytest.mark.parametrize('text', ['', ',', 'two', '1,two', '1.5', '1-3'])
def test_id_list_rejects_what_is_not_a_list_of_ids(text):
    """argparse turns ArgumentTypeError into a usage error, not a traceback."""
    with pytest.raises(argparse.ArgumentTypeError):
        id_list(text)


def test_tonii_converts_every_listed_scan(h2_study, tmp_path):
    """-s takes a list: each named scan is converted, and nothing else is."""
    study = BrukerLoader(str(h2_study))
    # Two convertible, non-localizer scans of the sample study.
    from pvraw.scripts.pvraw import is_localizer
    wanted = [sid for sid, recos in study.avail_reco_id.items()
              if not is_localizer(study, sid, recos[0])][:2]
    assert len(wanted) == 2

    subprocess.check_call(['pvraw', 'tonii', str(h2_study),
                           '-s', ','.join(map(str, wanted)),
                           '-o', str(tmp_path / 'out')])

    # One scan can write several files (multi-slicepack, multi-echo), so the check is
    # which scans were written, not how many files: `out-<scan>-<reco>-<name>.nii.gz`.
    written = [p.name for p in tmp_path.glob('out-*.nii.gz')]
    assert {name.split('-')[1] for name in written} == {f'{sid:02d}' for sid in wanted}


def test_tonii_reports_an_id_the_study_does_not_have(h2_study, tmp_path):
    """A bad id in the list is reported and skipped, not a traceback, and the
    good ids in the same list still convert."""
    study = BrukerLoader(str(h2_study))
    from pvraw.scripts.pvraw import is_localizer
    good = next(sid for sid, recos in study.avail_reco_id.items()
                if not is_localizer(study, sid, recos[0]))
    missing = max(study.avail_reco_id) + 1

    out = subprocess.run(['pvraw', 'tonii', str(h2_study),
                          '-s', f'{good},{missing}', '-r', '1,99',
                          '-o', str(tmp_path / 'out')],
                         capture_output=True, text=True, check=True)

    assert f'No ScanID:{missing}' in out.stdout
    assert f'No RecoID:99 for ScanID:{good}' in out.stdout
    written = [p.name for p in tmp_path.glob('out-*.nii.gz')]
    assert {name.split('-')[1] for name in written} == {f'{good:02d}'}
