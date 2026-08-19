"""Tests for the command-line interface (scripts/pvraw.py).

The id-list parsing and the info error contract are pure-unit (offline). The
selection and info-output tests run the real CLI against a public sample
study, so they carry the ``data`` marker through their fixture.
"""
import argparse
import json
import re
import subprocess
import sys

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


def test_info_rejects_a_missing_input(tmp_path, monkeypatch, capsys):
    """A path that is no PvDataset is an error contract: stderr and exit 1,
    nothing on stdout -- `--json` consumers must be able to trust stdout."""
    from pvraw.scripts.pvraw import main
    monkeypatch.setattr(sys, 'argv', ['pvraw', 'info', '--json',
                                      str(tmp_path / 'no_such_study')])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'not valid' in captured.err


def test_info_json_is_parseable_and_shaped(h2_study):
    out = subprocess.run(['pvraw', 'info', '--json', str(h2_study)],
                         capture_output=True, text=True, check=True)
    info = json.loads(out.stdout)
    assert set(info) == {'study', 'scans'}
    assert info['study']['pv_version']
    assert info['scans']
    for scan in info['scans']:
        assert isinstance(scan['scan_id'], int)
        for reco in scan['recos']:
            assert isinstance(reco['reco_id'], int)
    recos = [r for s in info['scans'] for r in s['recos'] if 'error' not in r]
    assert recos
    # the enriched fields ride on every readable reconstruction
    assert all({'dim_class', 'frame_groups', 'derived', 'bids', 'warns'} <= set(r)
               for r in recos)
    assert any(r['shape'] for r in recos)
    # at least one scan of the sample study predicts a BIDS conversion
    assert any(r['bids'] for r in recos)


def test_info_json_dates_are_iso(lego_study):
    """The study date and dob are ISO 8601, not ParaVision's spellings
    ('28 Feb 2020'). The lego study records both; h2 (PV5.1) writes no dob."""
    out = subprocess.run(['pvraw', 'info', '--json', str(lego_study)],
                         capture_output=True, text=True, check=True)
    study = json.loads(out.stdout)['study']
    assert study['dob'] == '2020-02-28'
    assert study['date'].startswith('2020-06-12T')


def test_info_text_summarises_the_study(h2_study):
    out = subprocess.run(['pvraw', 'info', str(h2_study)],
                         capture_output=True, text=True, check=True)
    assert 'Paravision' in out.stdout
    assert re.search(r'^\[\d{3}\]', out.stdout, re.MULTILINE)
    assert 'matrix_size' in out.stdout


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
