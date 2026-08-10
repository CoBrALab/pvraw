"""Unit tests for the BIDS modality-agnostic tables (lib/tabular.py).

Pure-unit (offline): the module takes parameter objects, not a loader, so every
row can be built from a stub.
"""
import datetime as dt

import pytest

from brkraw_legacy.lib import tabular


class _p(dict):
    """A stub subject/visu_pars: a JCAMPDX's read accessors over a dict."""
    def __init__(self, **params):
        super().__init__(params)

    def get_parameter(self, key):
        from types import SimpleNamespace
        return SimpleNamespace(value=self[key], nested=self[key], val_str=str(self[key]))


# --- date handling -----------------------------------------------------------

# Naive datetimes on purpose: ParaVision records scanner wall-clock with no zone,
# so attaching one would shift the time (see lib/tabular.parse_datetime).
@pytest.mark.parametrize(('raw', 'expected'), [
    ('2020-06-12T10:09:12,758+0200', dt.datetime(2020, 6, 12, 10, 9, 12)),  # noqa: DTZ001
    ('14:15:17 16 Jun 2020', dt.datetime(2020, 6, 16, 14, 15, 17)),         # noqa: DTZ001
    ('not a date', None),
    (None, None),
])
def test_parse_datetime_handles_both_paravision_forms(raw, expected):
    assert tabular.parse_datetime(raw) == expected


def test_acq_time_uses_the_acquisition_not_the_reconstruction():
    """VisuAcqDate is when the acquisition started, which is what BIDS asks for.

    VisuCreationDate is when the reconstruction was written, and get_scan_time's
    ``scan_time`` adds the duration, so it is the end rather than the start.
    """
    visu = _p(VisuAcqDate='2020-06-12T10:09:12,758+0200',
              VisuCreationDate='2020-06-12T10:10:59,993+0200')
    assert tabular.acq_time(visu) == '2020-06-12T10:09:12'


def test_acq_time_emits_no_offset_or_fraction():
    """Both are optional in the BIDS datetime format, and Bruker's zone is a guess:
    the scanner records wall clock, so attaching one would shift the time."""
    value = tabular.acq_time(_p(VisuAcqDate='2021-01-28T12:49:58,048+0100'))
    assert value == '2021-01-28T12:49:58'
    assert '+' not in value and ',' not in value and '.' not in value


# --- participants ------------------------------------------------------------

@pytest.mark.parametrize(('params', 'expected'), [
    ({'SUBJECT_sex_animal': 'MALE'}, 'male'),
    ({'SUBJECT_sex_animal': 'FEMALE'}, 'female'),
    ({'SUBJECT_sex_human': 'Male'}, 'male'),
    ({'SUBJECT_gender': 'female'}, 'female'),       # PV360 spelling
    ({'SUBJECT_sex': 'female'}, 'female'),          # PV5.1 display duplicate
    ({'SUBJECT_sex_animal': 'UNKNOWN'}, None),      # absence, not a third value
    ({'SUBJECT_sex_animal': 'UNDEFINED'}, None),
    ({}, None),
])
def test_sex_normalised_to_the_bids_vocabulary(params, expected):
    assert tabular.sex(_p(**params)) == expected


@pytest.mark.parametrize(('params', 'expected'), [
    ({'SUBJECT_weight': 0.0251}, 0.0251),           # a mouse
    ({'SUBJECT_study_weight': 5.0}, 5.0),           # PV360 spelling
    ({'SUBJECT_weight': 0.001}, None),              # ParaVision's unset sentinel
    ({'SUBJECT_weight': 0}, None),
    ({}, None),
])
def test_weight_treats_the_sentinel_as_absent(params, expected):
    assert tabular.weight_kg(_p(**params)) == expected


def test_age_is_derived_and_the_birth_date_is_never_returned():
    """BIDS has an age column and no birth-date column. The age is the fact worth
    keeping; the birth date is only its source."""
    subject = _p(SUBJECT_dbirth='28 Feb 2020', SUBJECT_date='2020-06-12T09:46:25,256+0200')
    assert tabular.age_years(subject) == pytest.approx(0.287, abs=0.001)

    row = tabular.participant_row(subject, 'sub-01')
    assert 'dbirth' not in ' '.join(map(str, row)).lower()
    assert not any('2020-02-28' in str(v) or '28 Feb 2020' in str(v) for v in row.values())


@pytest.mark.parametrize(('params', 'expected'), [
    ({'SUBJECT_dbirth': '28 Feb 2020'}, None),                       # no scan date
    ({'SUBJECT_date': '2020-06-12T09:46:25,256+0200'}, None),        # no birth date
    ({}, None),
])
def test_age_absent_when_either_half_is_missing(params, expected):
    assert tabular.age_years(_p(**params)) == expected


@pytest.mark.parametrize(('subject_type', 'expected'), [
    ('Biped', False),                                            # primate frame
    ('Quadruped', True), ('OtherAnimal', True), ('Other', True), ('Phantom', True),
    (None, True),                                                # PV5.1: no type at all
])
def test_non_human_read_from_the_subject_frame(subject_type, expected):
    """The taxon comes from the frame the scan was acquired in, per scan.

    An absent type means rodent, matching the affine's own rule -- which is why
    PV5.1, where VisuSubjectType does not exist, resolves to non-human.
    """
    visu = _p() if subject_type is None else _p(VisuSubjectType=subject_type)
    assert tabular.is_non_human(visu) is expected


def test_non_human_ignores_the_pv51_subject_file():
    """PV5.1 writes SUBJECT_type=Human for every study regardless of specimen.

    Reading it would report human for the rodent data that is most of PV5.1 --
    the same trap test_pv5_subject_type_not_taken_from_subject_file guards for
    geometry. A PV5.1 scan has no VisuSubjectType, so it must resolve to non-human
    even when the study subject file shouts Human.
    """
    assert tabular.is_non_human(_p(SUBJECT_type='Human')) is True


def test_species_is_written_as_na_rather_than_omitted():
    """BIDS reads an ABSENT species column as `homo sapiens`. Leaving it out would
    make every animal dataset silently claim to be human, so it is written as n/a
    and the converter warns."""
    row = tabular.participant_row(_p(SUBJECT_type='Quadruped'), 'sub-01')
    assert row['species'] == tabular.NA
    assert 'species' in tabular.PARTICIPANT_COLUMNS


# --- writing -----------------------------------------------------------------

def test_write_tsv_uses_na_for_absence(tmp_path):
    path = tmp_path / 'participants.tsv'
    tabular.write_tsv(path, tabular.PARTICIPANT_COLUMNS, [
        {'participant_id': 'sub-01', 'species': 'n/a', 'age': None, 'sex': 'female',
         'weight': 0.0251},
    ])
    lines = path.read_text().splitlines()
    assert lines[0] == 'participant_id\tspecies\tage\tsex\tweight'
    assert lines[1] == 'sub-01\tn/a\tn/a\tfemale\t0.0251'


def test_every_participant_column_is_described(tmp_path):
    """An undescribed non-standard column is a validator warning, and `weight` is
    not a BIDS-defined column."""
    described = set(tabular.PARTICIPANT_DESCRIPTIONS) | {'participant_id'}
    assert set(tabular.PARTICIPANT_COLUMNS) <= described


def test_rerunning_into_an_existing_tree_is_allowed(tmp_path):
    """Writing the modality-agnostic files twice must not abort.

    It used to call sys.exit() when participants.tsv already existed, so a subject
    could never be added to a converted dataset.
    """
    from brkraw_legacy.scripts.brkraw_legacy import generateModalityAgnosticFiles

    generateModalityAgnosticFiles(str(tmp_path), None)
    generateModalityAgnosticFiles(str(tmp_path), None)   # must not raise SystemExit
    assert (tmp_path / 'dataset_description.json').exists()


def test_participant_sidecar_is_not_written_without_its_table(tmp_path):
    """participants.json must not appear before participants.tsv exists.

    A study whose every scan is unclassifiable produces no participant rows, so no
    table -- and a sidecar written up front is then left describing a file that
    does not exist. The full-corpus sweep caught this on 11 units, all of them
    studies where nothing reaches the validated tree.
    """
    from brkraw_legacy.scripts.brkraw_legacy import (
        generateModalityAgnosticFiles,
        writeParticipantTables,
    )

    generateModalityAgnosticFiles(str(tmp_path), None)
    assert not (tmp_path / 'participants.json').exists()

    writeParticipantTables(str(tmp_path), [], {}, {})       # nothing converted
    assert not (tmp_path / 'participants.json').exists()
    assert not (tmp_path / 'participants.tsv').exists()

    writeParticipantTables(str(tmp_path),
                           [{'participant_id': 'sub-01'}], {}, {})
    assert (tmp_path / 'participants.tsv').exists()
    assert (tmp_path / 'participants.json').exists()
