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


def test_study_identity_matches_every_dataset(h2_study, lego_study):
    """The study identity in ``info_dict`` equals `brukerapi`'s Dataset
    properties on every reconstruction -- one id vocabulary with brukerapi's
    ``report()``, the invariant the switch to those properties buys (#94).
    Covers PV5.1 (h2) and PV6 (lego)."""
    for root in (h2_study, lego_study):
        study = BrukerLoader(str(root))
        block = study.info_dict()['study']
        for scan_id, recos in study.avail_reco_id.items():
            for reco_id in recos:
                dataset = study.study.get_scan(scan_id).get_dataset(reco_id)
                assert dataset.get('subj_id') == block['subject_id']
                assert dataset.get('study_id') == block['study_name']
                assert dataset.get('study_nr') == block['study_nr']


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


# --------------------------------------------------------------------------- #
# The BIDS session is ParaVision's session number, which only the study
# directory name carries (ADR 0003).
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('name, expected', [
    ('20260821_134720_MCHxFRTx001_2_1', (2, 1)),        # second visit, template 1
    ('20260821_140024_MCHxFRTx002_1_2', (1, 2)),        # first visit, template 2
    ('20251219_142450_MCH_AONP_IC118_4_1_1', (1, 1)),   # underscores in the Animal ID
    ('MCHxFRTx001_20260821_134720_3_1', (3, 1)),        # the $AnimalID_$Date_$Time pattern
    ('20240524_163824_legophantom1_1_1', (1, 1)),
    ('0.2H2', None),                                    # PV5.1: no session suffix
    ('sub01_baseline', None),                           # renamed by hand
])
def test_session_and_study_number_come_from_the_directory_name(name, expected):
    from pvraw.lib.loader import session_and_study_number
    assert session_and_study_number(name) == expected


def test_session_id_is_the_session_not_the_study_number(lego_study):
    """``..._lego_phantom_3_1_2``: session 1, study 2 -- the old code returned 2."""
    from pvraw import BrukerLoader
    study = BrukerLoader(str(lego_study))
    assert study.session_id == 1
    assert study.study_nr == 2
    assert study.info_dict()['study']['session'] == 1


def test_info_text_labels_say_whose_attribute_each_field_is():
    """Offline: the study block is rendered from the dict alone."""
    from pvraw.lib.loader import BrukerLoader
    info = {'study': {'pv_version': '360.3.7', 'user_account': 'nmrsu', 'operator': 'jkl',
                      'subject_name': 'std_PV360_3.7^^^^', 'subject_id': 'std_PV360_3.7',
                      'position': 'Head_Prone', 'use_ats': 'Yes'},
            'scans': [{'scan_id': 23, 'tr_ms': 200, 'te_ms': 3, 'acq_date': '2025-08-14T10:29:19',
                       'nucleus': '1H', 'num_averages': 3, 'recos': []}]}
    text = '\n'.join(BrukerLoader._render_info(info))
    assert 'Researcher' not in text
    assert 'Subject Name:  std_PV360_3.7^^^^' in text
    assert 'User Account:  nmrsu' in text and 'Operator:      jkl' in text
    assert 'ATS:           Yes' in text
    assert '[ acquired: 2025-08-14T10:29:19, nucleus: 1H, NA: 3 ]' in text


def test_info_json_study_block_is_version_independent(lego_study, h2_study):
    """The same keys and vocabulary on PV6 and PV5.1: the operator comes from
    SUBJECT_referral, the position is spelled as --position takes it."""
    from pvraw import BrukerLoader
    lego = BrukerLoader(str(lego_study)).info_dict()['study']
    assert lego['subject_name'] == 'lego_phantom_3' and lego['subject_id'] == 'lego_phantom_3'
    assert lego['user_account'] == 'psorn' and lego['operator'] == 'psorn'
    assert lego['study_name'] == 'data_io'
    assert lego['position'] == 'Head_Prone'          # SUBJ_ENTRY_HeadFirst + SUBJ_POS_Prone
    assert lego['institution'] and lego['station']
    h2 = BrukerLoader(str(h2_study)).info_dict()['study']
    assert h2['subject_name'] == 'LEGO_PHANTOM' and h2['operator'] is None
    assert h2['position'] == 'Head_Supine'
    assert set(h2) == set(lego)
