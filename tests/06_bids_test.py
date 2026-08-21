"""BIDS path-builder and end-to-end conversion tests.

The unit tests exercise ``pvraw.lib.bids`` directly and need no sample
data. The end-to-end tests convert a public sample study (lego_phantom); the
validator check is skipped unless the ``bids-validator`` (Deno) binary is
available.
"""
import itertools
import json
import shutil
import subprocess

import pytest

from pvraw.lib import bids
from pvraw.lib.errors import InvalidApproach
from pvraw.scripts.pvraw import scanMethod

# --------------------------------------------------------------------------- #
# Unit tests: schema-driven path builder
# --------------------------------------------------------------------------- #

def test_entity_order_rec_before_dir():
    """Regression: the old code emitted dir- before rec-, violating the spec."""
    ents = {'subject': '01', 'task': 't', 'acquisition': 'hi', 'ceagent': 'gd',
                'reconstruction': 'x', 'direction': 'AP'}
    _, stem = bids.build_path(ents, 'func', 'bold')
    assert stem == 'sub-01_task-t_acq-hi_ce-gd_rec-x_dir-AP_bold'
    assert stem.index('_rec-') < stem.index('_dir-')


def test_func_suffix_is_lowercase_bold():
    rel_dir, stem = bids.build_path({'subject': '01', 'task': 'rest'}, 'func', 'bold')
    assert rel_dir == 'sub-01/func'
    assert stem.endswith('_bold')


def test_session_in_path_and_name():
    rel_dir, stem = bids.build_path({'subject': '01', 'session': 'pre', 'task': 'rest'},
                                    'func', 'bold')
    assert rel_dir == 'sub-01/ses-pre/func'
    assert stem.startswith('sub-01_ses-pre_')


def test_anat_and_dwi_and_fmap_paths():
    assert bids.build_path({'subject': '01'}, 'anat', 'T2w') == ('sub-01/anat', 'sub-01_T2w')
    assert bids.build_path({'subject': '01'}, 'dwi', 'dwi') == ('sub-01/dwi', 'sub-01_dwi')
    # bare `magnitude` is valid in the schema (pybids' bundled patterns wrongly reject it)
    assert bids.build_path({'subject': '01'}, 'fmap', 'magnitude') == ('sub-01/fmap', 'sub-01_magnitude')
    assert bids.build_path({'subject': '01'}, 'fmap', 'fieldmap') == ('sub-01/fmap', 'sub-01_fieldmap')


def test_invalid_suffix_rejected():
    with pytest.raises(InvalidApproach):
        bids.build_path({'subject': '01'}, 'func', 'EPI')        # method-derived junk
    with pytest.raises(InvalidApproach):
        bids.build_path({'subject': '01'}, 'etc', 'whatever')    # not a BIDS datatype


def test_default_suffix_mapping():
    assert bids.default_suffix('func', 'epi:EPI') == 'bold'
    assert bids.default_suffix('dwi', 'dti:DtiEpi') == 'dwi'
    assert bids.default_suffix('anat', 'x:FLASH') == 'FLASH'
    assert bids.default_suffix('anat', 'x:RARE') == 'T2w'
    assert bids.default_suffix('anat', 'x:MSME') == 'MESE'
    assert bids.default_suffix('etc', 'something') is None        # unknown -> no suffix


def test_build_prefix_excludes_run_echo_and_suffix():
    """FileName carries the prefix; run/echo/suffix are appended downstream."""
    _rel_dir, prefix = bids.build_prefix({'subject': '01', 'task': 'rest', 'run': '02', 'echo': '1'},
                                         'func')
    assert prefix == 'sub-01_task-rest'
    assert 'run-' not in prefix and 'echo-' not in prefix


def test_label_validation():
    assert bids.is_valid_label('abc123')
    assert not bids.is_valid_label('a_b')
    assert not bids.is_valid_label('a-b')


def test_bids_version_comes_from_the_schema_not_a_literal():
    """``BIDSVersion`` must track the schema we validate against.

    Regression: three places hardcoded '1.10.0' while the loaded schema was 1.11.1,
    so every converted dataset claimed a version it was never checked against. This
    runs offline, unlike the end-to-end check that reads the written sidecar.
    """
    import re

    from pvraw.lib.reference import DATASET_DESC_REF

    assert re.fullmatch(r'\d+\.\d+\.\d+', bids.BIDS_VERSION), bids.BIDS_VERSION
    # The template must not carry a version of its own to drift from the schema.
    assert DATASET_DESC_REF['BIDSVersion'] == ''


# --------------------------------------------------------------------------- #
# Sidecar value checking (offline: no sample data, no validator binary)
# --------------------------------------------------------------------------- #

def test_value_problem_accepts_valid_values():
    for field, value in [('RepetitionTime', 2.0), ('PhaseEncodingDirection', 'j'),
                         ('SliceTiming', [0.0, 0.1, 0.2]), ('EchoTime', 0.03),
                         ('EchoTime', [0.01, 0.02]), ('MRAcquisitionType', '2D'),
                         ('FlipAngle', 30), ('Units', 'Hz'), ('M0Type', 'Absent')]:
        assert bids.value_problem(field, value) is None, (field, value)


@pytest.mark.parametrize(('field', 'value'), [
    ('SoftwareVersions', 6.0),            # Bruker <6.0> parses to a float, not a string
    ('InversionTime', [0.5, 1.0]),        # multi-TI array where BIDS wants one number
    ('FlipAngle', 0),                     # must be > 0
    ('PhaseEncodingDirection', 'col_dir'),  # raw PV5.1 code reaching the sidecar
    ('MRAcquisitionType', '2'),           # enum is 1D/2D/3D
    ('RepetitionTime', -1.0),             # must be > 0
    ('SliceTiming', [0.0, 'x']),          # array items must be numbers
    ('M0Type', 'absent'),                 # enum is case-sensitive
    ('IntendedFor', '*_bold.nii.gz'),     # a glob is not a valid BIDS path
])
def test_value_problem_catches_every_historical_bug_class(field, value):
    """Each case here was a real sidecar bug found and fixed by hand.

    They are all type/unit/enum errors, which is exactly what the schema's
    ``objects/metadata`` definitions constrain -- so a value check would have caught
    the lot without a dataset or a validator run.
    """
    assert bids.value_problem(field, value) is not None


def test_value_problem_ignores_names_the_schema_does_not_define():
    """A sidecar may carry non-BIDS keys; judging those is not this check's business.

    ``CoilConfigName`` is one we emit on purpose (see lib/reference.py).
    """
    assert bids.value_problem('CoilConfigName', 'anything') is None


def test_invalid_value_is_demoted_rather_than_written_or_dropped():
    """An invalid value must not reach its BIDS key, and must not vanish either.

    Writing it earns a JSON_SCHEMA_VALIDATION_ERROR (severity error); dropping it
    loses a real Bruker reading. It is kept under a name that is honestly not BIDS.
    """
    import warnings

    from pvraw.lib.loader import _demote_schema_invalid

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        out = _demote_schema_invalid(
            {'RepetitionTime': 2.0, 'FlipAngle': 0, 'CoilConfigName': 'x'}, 'demo')

    assert out == {'RepetitionTime': 2.0, 'FlipAngleRaw': 0, 'CoilConfigName': 'x'}
    assert 'FlipAngle' not in out                      # not written under the BIDS key
    assert any('FlipAngle' in str(w.message) for w in caught)


# --------------------------------------------------------------------------- #
# Fieldmap pairing
# --------------------------------------------------------------------------- #

def _row(name, time, group=None):
    return {'filename': name, 'acq_time': time, 'b0group': group}


def test_fieldmap_claims_only_what_follows_it():
    """A fieldmap corrects what comes after it, not the whole session.

    Taken from the PV6 corpus study, where three dwi runs precede the fieldmap by
    about an hour and one follows it. Claiming every dwi in the session -- the
    obvious rule -- would wrongly attach a fieldmap to scans acquired before it
    was measured.
    """
    rows = [
        _row('dwi/sub-01_run-01_dwi.nii.gz', '2020-06-12T11:12:52'),
        _row('dwi/sub-01_run-02_dwi.nii.gz', '2020-06-12T11:26:35'),
        _row('dwi/sub-01_run-03_dwi.nii.gz', '2020-06-12T11:40:17'),
        _row('fmap/sub-01_fieldmap.nii.gz', '2020-06-12T12:28:15'),
        _row('dwi/sub-01_run-04_dwi.nii.gz', '2020-06-12T13:38:22'),
    ]
    assert bids.pair_fieldmaps(rows) == {
        'fmap/sub-01_fieldmap.nii.gz': ['dwi/sub-01_run-04_dwi.nii.gz'],
    }


def test_each_fieldmap_claims_its_own_window():
    """The normal case a session-wide rule gets wrong: two fieldmaps."""
    rows = [
        _row('fmap/sub-01_run-01_fieldmap.nii.gz', '2020-01-01T10:00:00'),
        _row('func/sub-01_task-a_bold.nii.gz', '2020-01-01T10:10:00'),
        _row('fmap/sub-01_run-02_fieldmap.nii.gz', '2020-01-01T11:00:00'),
        _row('func/sub-01_task-b_bold.nii.gz', '2020-01-01T11:10:00'),
    ]
    assert bids.pair_fieldmaps(rows) == {
        'fmap/sub-01_run-01_fieldmap.nii.gz': ['func/sub-01_task-a_bold.nii.gz'],
        'fmap/sub-01_run-02_fieldmap.nii.gz': ['func/sub-01_task-b_bold.nii.gz'],
    }


def test_anatomical_scans_are_never_claimed():
    """Anat is not an EPI readout; naming it would claim a correction nobody applies."""
    rows = [
        _row('fmap/sub-01_fieldmap.nii.gz', '2020-01-01T10:00:00'),
        _row('anat/sub-01_T2w.nii.gz', '2020-01-01T10:10:00'),
        _row('anat/sub-01_T1map.nii.gz', '2020-01-01T10:20:00'),
    ]
    assert bids.pair_fieldmaps(rows) == {'fmap/sub-01_fieldmap.nii.gz': []}


def test_datasheet_label_overrides_acquisition_order():
    """The operator knows what the fieldmap was for; the clock does not.

    Here the label deliberately pairs the fieldmap with a scan acquired BEFORE it,
    which the time rule would never do.
    """
    rows = [
        _row('dwi/sub-01_run-01_dwi.nii.gz', '2020-01-01T10:00:00', group='pair1'),
        _row('fmap/sub-01_fieldmap.nii.gz', '2020-01-01T11:00:00', group='pair1'),
        _row('dwi/sub-01_run-02_dwi.nii.gz', '2020-01-01T12:00:00'),
    ]
    assert bids.pair_fieldmaps(rows) == {
        'fmap/sub-01_fieldmap.nii.gz': ['dwi/sub-01_run-01_dwi.nii.gz'],
    }


@pytest.mark.parametrize(('filename', 'expected'), [
    ('anat/sub-01_ses-2_run-01_T2w.nii.gz', 'T2w'),
    ('fmap/sub-01_fieldmap.nii.gz', 'fieldmap'),
    ('dwi/sub-01_run-04_dwi.nii.gz', 'dwi'),
])
def test_suffix_of(filename, expected):
    assert bids.suffix_of(filename) == expected


# --------------------------------------------------------------------------- #
# Unit tests: conversion prediction (info --json's `bids` field, and the
# rules behind bids_helper's datasheet prefill)
# --------------------------------------------------------------------------- #

class _Params(dict):
    """A parameter file fake speaking `get_value`'s protocol."""
    def get_parameter(self, key):
        return _Value(self[key])


class _Value:
    def __init__(self, value):
        self.value = value
        self.val_str = str(value)
        self.nested = value


@pytest.mark.parametrize(('method', 'datatype'), [
    ('Bruker:EPI', 'func'),
    ('Bruker:DtiEpi', 'dwi'),          # 'dti' outranks the 'epi' substring
    ('Bruker:FLASH', 'anat'),
    ('Bruker:RARE', 'anat'),
    ('Bruker:FieldMap', 'fmap'),
    ('Bruker:MSME', 'anat'),
    ('Bruker:SINGLEPULSE', 'etc'),
])
def test_datatype_of_method(method, datatype):
    assert bids.datatype_of_method(method) == datatype


def _predict(method_name, extra=None, visu=None, groups=()):
    method = _Params({'Method': method_name, **(extra or {})})
    return bids.predict_conversion(method, _Params(visu or {}), list(groups))


def test_predict_localizer_is_not_converted():
    visu = {'VisuAcquisitionProtocol': 'TriPilot-multi'}
    assert _predict('Bruker:FLASH', visu=visu) is None


def test_predict_epi_needs_more_than_one_volume():
    assert _predict('Bruker:EPI', {'PVM_NRepetitions': 300}) == \
        {'datatype': 'func', 'suffix': 'bold'}
    assert _predict('Bruker:EPI', {'PVM_NRepetitions': 1}) is None


def test_predict_fair_outranks_the_epi_substring():
    """FAIR_EPI is perfusion, not a functional run."""
    assert _predict('Bruker:FAIR_EPI') == {'datatype': 'perf', 'suffix': 'asl'}


def test_predict_dti_and_anat():
    assert _predict('Bruker:DtiEpi') == {'datatype': 'dwi', 'suffix': 'dwi'}
    assert _predict('Bruker:FLASH') == {'datatype': 'anat', 'suffix': 'FLASH'}
    assert _predict('Bruker:RARE') == {'datatype': 'anat', 'suffix': 'T2w'}


def test_predict_msme_is_mese_only_when_multi_echo():
    assert _predict('Bruker:MSME', groups=[('echo', 12)]) == \
        {'datatype': 'anat', 'suffix': 'MESE'}
    assert _predict('Bruker:MSME', groups=[('echo', 1)]) == \
        {'datatype': 'anat', 'suffix': 'T2w'}


def test_predict_fieldmap_names_no_single_suffix():
    """A Bruker field map converts to a fieldmap/magnitude pair."""
    assert _predict('Bruker:FieldMap') == {'datatype': 'fmap', 'suffix': None}


def test_predict_unrecognised_method_predicts_nothing():
    assert _predict('Bruker:SINGLEPULSE') is None


def test_predict_derived_stack_only_when_it_is_a_map():
    """A derived reconstruction converts only when one element is a known map."""
    visu = {'VisuFGElemComment': ['fitted image', 'T2 relaxation time',
                                  'standard deviation', 'RSS', 'DOF']}
    assert _predict('Bruker:MSME', visu=visu, groups=[('isa', 5)]) == \
        {'datatype': 'anat', 'suffix': 'T2map'}
    assert _predict('Bruker:DtiEpi', groups=[('dti', 22)]) is None


# --------------------------------------------------------------------------- #
# The verdict table: every schema field is accounted for
# --------------------------------------------------------------------------- #

#: Rule groups covering the datatypes this converter emits. `asl` is deliberately
#: absent until the perf datatype lands; add it with that work, not before.
_VERDICT_GROUPS = ('mri', 'anat', 'func', 'dwi', 'fmap', 'qmri', 'entity_rules')


def _schema_sidecar_fields():
    """Every sidecar field named by a rule group for a datatype we can emit."""
    names = set()
    for group in _VERDICT_GROUPS:
        for rule in bids._SCHEMA.rules.sidecars[group].values():
            for field in rule.get('fields', {}):
                # A few names are disambiguated per modality in the schema
                # (`AnatomicalLandmarkCoordinates__mri`); the sidecar key is the stem.
                names.add(field.split('__')[0])
    return names


def _verdicts():
    from pvraw.lib import reference as ref

    mapped = set()
    for table in (ref.COMMON_META_REF, ref.FMRI_META_REF, ref.FIELDMAP_META_REF):
        mapped |= {k for k, v in table.items() if v is not None}
    return {
        'mapped': mapped,
        'computed at write time': set(ref.COMPUTED_AT_WRITE),
        'source known, not yet mapped': set(ref.UNMAPPED_WITH_SOURCE),
        'no Bruker source': set(ref.NO_BRUKER_SOURCE),
    }


def test_every_schema_field_has_a_verdict():
    """No BIDS field may be silently unaccounted for.

    Each one is mapped, computed at write time, known-but-unmapped (the gap list),
    or recorded as having no Bruker source *with the reason*. A `bidsschematools`
    bump that introduces a field then shows up as a failing test rather than as
    metadata quietly going missing -- which is the whole point, since the reference
    validator says nothing about a missing OPTIONAL field.
    """
    verdicts = _verdicts()
    accounted = set().union(*verdicts.values())
    missing = sorted(_schema_sidecar_fields() - accounted)
    assert not missing, (
        'schema fields with no verdict in lib/reference.py: ' + ', '.join(missing))


def test_no_field_carries_two_verdicts():
    """A field is in exactly one state; two would make the gap list a guess."""
    verdicts = _verdicts()
    for a, b in itertools.combinations(sorted(verdicts), 2):
        overlap = sorted(verdicts[a] & verdicts[b])
        assert not overlap, f"'{a}' and '{b}' both claim: {', '.join(overlap)}"


def test_keys_we_emit_are_either_bids_or_declared_non_bids():
    """A key that is neither a BIDS field nor a declared exception is a typo."""
    from pvraw.lib import reference as ref

    emitted = _verdicts()['mapped'] | set(ref.COMPUTED_AT_WRITE)
    undeclared = sorted(emitted - set(bids._SCHEMA.objects.metadata) - set(ref.NON_SCHEMA_KEYS))
    assert not undeclared, (
        'emitted keys that BIDS does not define and NON_SCHEMA_KEYS does not '
        'declare: ' + ', '.join(undeclared))


def test_no_deprecated_field_is_emitted():
    """Deprecated means the spec is removing it; extracting more is not extracting worse."""
    emitted = _verdicts()['mapped'] | set(_verdicts()['computed at write time'])
    deprecated = set()
    for group in _VERDICT_GROUPS:
        for rule in bids._SCHEMA.rules.sidecars[group].values():
            for field, spec in rule.get('fields', {}).items():
                level = spec if isinstance(spec, str) else spec.get('level')
                if level == 'deprecated':
                    deprecated.add(field.split('__')[0])
    # AcquisitionDuration is deprecated for func only, and is dropped in the func
    # merge (lib/utils.get_bids_ref_obj); it stays optional -- and emitted -- elsewhere.
    assert emitted & deprecated <= {'AcquisitionDuration'}


def test_subject_session_id_sanitized_to_valid_bids_label():
    """A subject/session ID must become an alphanumeric BIDS label. Regression:
    a version-derived id like PV360's ``std_PV360_3.7`` kept its '.', which is
    invalid in a sub-<label> and made the whole subject tree unrecognizable."""
    import re
    import warnings

    from pvraw.scripts.pvraw import cleanSessionID, cleanSubjectID

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        assert cleanSubjectID('std_PV360_3.7') == 'stdUnderscorePV360Underscore37'
        assert cleanSessionID('1.2') == '12'
        assert cleanSubjectID('clean123') == 'clean123'   # unchanged
        for raw in ('a.b', 'x_3.7', 'p 1', 'v/2'):
            assert re.fullmatch(r'[a-zA-Z0-9]+', cleanSubjectID(raw)), raw


# --------------------------------------------------------------------------- #
# End-to-end: convert a public dataset and validate it
# --------------------------------------------------------------------------- #

def _validator_bin():
    return shutil.which('bids-validator-deno') or shutil.which('bids-validator')


def _simple_scans(pvdir, count):
    """Up to `count` scan ids that convert to a single 3D image.

    Each yields one clean anat file rather than a per-slicepack
    _T2starw-01/-02/... split.
    """
    from pvraw import BrukerLoader

    loader = BrukerLoader(str(pvdir))
    simple = []
    for sid in loader.avail_scan_id:
        try:
            obj = loader.get_niftiobj(sid, 1)
        except Exception:
            continue
        if not isinstance(obj, list) and getattr(obj, 'ndim', 0) == 3:
            simple.append(sid)
        if len(simple) >= count:
            break
    assert simple, 'no single-volume 3D scan available for anat conversion'
    return simple


def _prepare_anat_dataset(pvdir, tmp_path):
    """Run bids_helper, fill in a couple of valid anat rows, and convert.

    The sample scans have no auto-classifiable BIDS datatype, so we rewrite two
    single-volume 3D scans as anat/T2starw to exercise a real, validatable
    conversion (multi-slicepack scouts would split into several files and are
    skipped). Only the chosen study is exposed (via a symlinked parent) so the
    helper converts just it.
    """
    import pandas as pd

    simple = _simple_scans(pvdir, 2)

    sample_parent = tmp_path / 'sample'
    sample_parent.mkdir()
    (sample_parent / pvdir.name).symlink_to(pvdir.resolve())
    sheet = tmp_path / 'bids_map'
    out = tmp_path / 'raw'

    subprocess.check_call(['pvraw', 'bids_helper', str(sample_parent),
                           str(sheet), '-j'])
    df = pd.read_csv(str(sheet) + '.csv')

    # First reco of each chosen scan -> anat T2starw with a distinguishing acq.
    first_recos = df[df['RecoID'] == df.groupby('ScanID')['RecoID'].transform('min')]
    df = first_recos[first_recos['ScanID'].isin(simple)].drop_duplicates('ScanID').copy()
    assert len(df) >= 1, 'no scans available in dataset'
    df['SubjID'] = '001'
    df['SessID'] = ''
    df['DataType'] = 'anat'
    df['modality'] = 'T2starw'
    df['acq'] = [f'scan{i}' for i in range(len(df))]
    df.to_csv(str(sheet) + '.csv', index=False)

    subprocess.check_call(['pvraw', 'bids_convert', str(sample_parent),
                           str(sheet) + '.csv', '-j', str(sheet) + '.json',
                           '--output', str(out)])
    return out


def test_end_to_end_bids_convert(lego_study, tmp_path):
    out = _prepare_anat_dataset(lego_study, tmp_path)

    # dataset_description.json: required keys, correct spelling, modern version
    desc = json.loads((out / 'dataset_description.json').read_text())
    # From the loaded schema, never a literal: the dataset must claim exactly the
    # version the validator below is pinned to.
    assert desc['BIDSVersion'] == bids.BIDS_VERSION
    assert desc['DatasetType'] == 'raw'
    assert any(g['Name'] == 'pvraw' for g in desc['GeneratedBy'])
    for typo in ('HowToAsknowledge', 'EthicApprovals', 'ReferenceAndLinks'):
        assert typo not in desc

    # At least one anat image + sidecar produced, in spec-correct location.
    niis = list(out.rglob('sub-001/anat/*_T2starw.nii.gz'))
    assert niis, 'expected anat NIfTI output'

    # No sidecar should contain placeholder junk, echoed parameter names or the
    # old invalid IntendedFor key/glob.
    for js in out.rglob('*.json'):
        text = js.read_text()
        assert 'Value was not specified' not in text
        assert 'IntendFor' not in text                 # old typo'd key
        assert '*_bold.nii.gz' not in text             # old invalid glob
        assert 'Visu' not in text                       # echoed Bruker param name


# A repeat visit under the same ParaVision study gets a new dataset directory
# but the same SUBJECT_study_nr, so bids_helper prefills both visits with one
# SessID. The helper must say so, and the converter must not let the second
# visit overwrite the first.

def test_helper_warns_when_two_datasets_share_a_scan_kind_in_one_session():
    from pvraw.scripts.pvraw import warnSessionCollisions

    later, earlier, other = ('20260821_134720_S1_1_2', '20260821_133357_S1_1_1',
                             '20260821_140024_S2_1_2')
    claims = {('S1', '1', 'anat', 'Bruker:FLASH', None): {later, earlier},   # collides
              ('S1', '1', 'func', 'Bruker:EPI', 'rest'): {later},            # one dataset: fine
              ('S2', '1', 'anat', 'Bruker:FLASH', None): {other}}
    dates = {later: '2026-08-21T13:47:20', earlier: '2026-08-21T13:33:57',
             other: '2026-08-21T14:00:24'}
    # one warning, for S1's anat only, listing its datasets oldest first
    with pytest.warns(UserWarning, match=rf'sub-S1 ses-1: anat Bruker:FLASH .*{earlier}.*{later}') as record:
        warnSessionCollisions(claims, dates)
    assert len(record) == 1


def test_claim_output_refuses_a_second_writer():
    from pvraw.lib.errors import ValueConflictInField
    from pvraw.scripts.pvraw import claimOutput

    claimed = {}
    claimOutput(claimed, '/out/sub-S1/ses-1/anat/sub-S1_ses-1_T1w', 'visit1')
    with pytest.raises(ValueConflictInField, match='visit1'):
        claimOutput(claimed, '/out/sub-S1/ses-1/anat/sub-S1_ses-1_T1w', 'visit2')


def test_repeat_visit_under_one_study_is_not_overwritten(lego_study, tmp_path):
    """The same study exposed twice under one session number."""
    import pandas as pd

    parent = tmp_path / 'sample'
    parent.mkdir()
    # Same session number (1) and study number (2) on purpose: ParaVision would
    # never write this pair, but a renamed or hand-copied directory can.
    visits = ('20200612_094625_lego_phantom_3_1_2', '20200613_094625_lego_phantom_3_1_2')
    for name in visits:
        (parent / name).symlink_to(lego_study.resolve())
    sheet = tmp_path / 'bids_map'

    helper = subprocess.run(['pvraw', 'bids_helper', str(parent), str(sheet)],
                            capture_output=True, text=True, check=True)
    assert 'comes from 2 datasets' in helper.stderr

    # One scan per visit, left on the SessID the helper prefilled for both.
    df = pd.read_csv(str(sheet) + '.csv', dtype={'SessID': str})
    df = df[df['ScanID'].isin(_simple_scans(lego_study, 2))] \
        .sort_values('RecoID').drop_duplicates(['RawData', 'ScanID'])
    df = df[df['ScanID'] == df['ScanID'].iloc[0]].copy()
    assert sorted(df['RawData']) == sorted(visits)
    assert df['SessID'].nunique() == 1
    df['DataType'] = 'anat'
    df['modality'] = 'T2starw'
    df.to_csv(str(sheet) + '.csv', index=False)

    out = tmp_path / 'raw'
    convert = subprocess.run(['pvraw', 'bids_convert', str(parent), str(sheet) + '.csv',
                              '--output', str(out)], capture_output=True, text=True, check=True)
    assert 'already wrote sub-' in convert.stdout
    assert len(list(out.rglob('sub-*/ses-*/anat/*_T2starw.nii.gz'))) == 1


def test_phase_encode_axis_emitted_without_a_polarity_claim(h2_study, tmp_path):
    """The PE axis ships as ``PhaseEncodingAxis``; BIDS ``PhaseEncodingDirection``
    must not appear at all.

    Two regressions in one. PV5.1's uniform ``VisuAcqImagePhaseEncDir`` of
    ``col_dir`` once reached the sidecar verbatim. And ``PhaseEncodingDirection``
    has no unsigned value -- the schema reads the polarity as positive unless '-'
    is present -- so emitting a bare 'j' claimed a sign we cannot derive.
    """
    valid_axes = {'i', 'j', 'k'}
    sample = tmp_path / 'sample'
    sample.mkdir()
    (sample / h2_study.name).symlink_to(h2_study.resolve())
    sheet = tmp_path / 'map'
    out = tmp_path / 'out'
    subprocess.check_call(['pvraw', 'bids_helper', str(sample), str(sheet), '-j'])
    subprocess.check_call(['pvraw', 'bids_convert', str(sample),
                           str(sheet) + '.csv', '-j', str(sheet) + '.json',
                           '--output', str(out)])
    seen = 0
    for js in out.rglob('*.json'):
        sidecar = json.loads(js.read_text())
        assert 'PhaseEncodingDirection' not in sidecar, f'{js.name} claims a PE polarity'
        axis = sidecar.get('PhaseEncodingAxis')
        if axis is not None:
            assert axis in valid_axes, f'{js.name}: {axis!r}'
            seen += 1
    if not seen:
        pytest.skip('no PhaseEncodingAxis emitted in this sample')


@pytest.mark.skipif(_validator_bin() is None, reason='bids-validator (deno) not available')
def test_end_to_end_passes_validator(lego_study, tmp_path):
    out = _prepare_anat_dataset(lego_study, tmp_path)

    # Pin the schema to the same release the dataset claims, rather than whatever the
    # validator happens to bundle: an unpinned run can go red on a spec release that
    # touched nothing here.
    proc = subprocess.run([_validator_bin(), str(out),
                           '--schema', f'v{bids.BIDS_VERSION}', '--json'],
                          capture_output=True, text=True, check=False)
    report = json.loads(proc.stdout or '{}')
    issues = report.get('issues', {})
    items = issues.get('issues', issues) if isinstance(issues, dict) else issues
    errors = [it for it in (items or []) if it.get('severity') == 'error']
    assert not errors, 'bids-validator reported errors: {}'.format(
        [(e.get('code'), e.get('subCode')) for e in errors])


def _two_small_3d_scans(study):
    """The two smallest scans of `study` that convert to a plain 3-D volume.

    Smallest first, so the sample study built from them stays a few megabytes
    and the search stops after a couple of conversions.
    """
    from pvraw import BrukerLoader

    by_size = sorted(
        (sum(f.stat().st_size for f in scan.rglob('*') if f.is_file()), scan.name)
        for scan in study.iterdir() if (scan / 'pdata').is_dir()
    )
    loader = BrukerLoader(str(study))
    found = []
    for _, name in by_size:
        try:
            obj = loader.get_niftiobj(int(name), 1)
        except Exception:
            continue
        if not isinstance(obj, list) and getattr(obj, 'ndim', 0) == 3:
            found.append(name)
            if len(found) == 2:
                return found
    pytest.skip('need two small 3-D scans to build the sample study')


def test_bids_convert_isolates_failing_scan(h2_study, tmp_path):
    """A scan that raises during conversion must be reported and skipped, not
    abort the whole study's BIDS conversion (mirrors tonii_all's per-scan guard).

    The failure is injected rather than looked for. This test used to hunt the
    sample study for a reconstruction that already crashed, and skipped itself
    when it found none -- which is what happened once the reading layer was
    delegated and the crashes were fixed, leaving the guard uncovered. Emptying
    a ``2dseq`` reproduces the condition on demand: it raises `InvalidDataset`,
    which is a genuine failure rather than the clean 'non-image data' skip that
    ``save_as`` handles by design.
    """
    import pandas as pd

    scans = _two_small_3d_scans(h2_study)
    sample = tmp_path / 'sample'
    study = sample / h2_study.name
    study.mkdir(parents=True)
    shutil.copy(h2_study / 'subject', study)
    for name in scans:
        shutil.copytree(h2_study / name, study / name)

    sheet = tmp_path / 'map'
    out = tmp_path / 'raw'
    subprocess.check_call(['pvraw', 'bids_helper', str(sample), str(sheet), '-j'])

    df = pd.read_csv(str(sheet) + '.csv')
    df = df[df['RecoID'] == 1].copy()
    df['SubjID'] = '001'
    df['SessID'] = ''
    df['DataType'] = 'anat'
    df['modality'] = 'T2starw'
    df['acq'] = [f'scan{scan}' for scan in df['ScanID']]
    df.to_csv(str(sheet) + '.csv', index=False)

    doomed, spared = int(df['ScanID'].iloc[0]), int(df['ScanID'].iloc[1])
    (study / str(doomed) / 'pdata' / '1' / '2dseq').write_bytes(b'')

    # Must not raise: the crashing scan is reported and skipped, not fatal.
    result = subprocess.run(['pvraw', 'bids_convert', str(sample),
                             str(sheet) + '.csv', '-j', str(sheet) + '.json',
                             '--output', str(out)],
                            check=True, capture_output=True, text=True)

    assert f'ScanID:{doomed}' in result.stdout, \
        f'the failing scan must be reported, not silently dropped:\n{result.stdout}'
    written = [p.name for p in out.rglob('sub-001/anat/*_T2starw.nii.gz')]
    assert f'sub-001_acq-scan{spared}_T2starw.nii.gz' in written, \
        f'the convertible scan should still produce output, got {written}'
    assert not any(f'scan{doomed}_' in name for name in written), \
        f'the failing scan must not produce output, got {written}'


def test_method_less_scan_does_not_crash(h2_study, tmp_path):
    """A scan carrying reconstruction data but no method file (e.g. an
    adjustment/reference scan) must be skipped with a warning, not crash
    bids_helper / tonii_all with a KeyError on the method lookup."""
    import shutil

    import pandas as pd

    from pvraw import BrukerLoader
    from pvraw.scripts.pvraw import is_localizer

    d = BrukerLoader(str(h2_study))

    def _scan_size(s):
        return sum(p.stat().st_size for p in (h2_study / str(s)).rglob('*') if p.is_file())

    def _listable(s):
        # a scan bids_helper would classify (image, non-localizer) -- i.e. one that
        # reaches the get_method() call the method-less guard protects
        if not (h2_study / str(s) / 'method').is_file():
            return False
        try:
            vp = d._get_visu_pars(s, 1)
            return d._get_dim_info(vp)[1] == 'spatial_only' and not is_localizer(d, s, 1)
        except Exception:
            return False

    scans = sorted((s for s in d.avail_scan_id if _listable(s)), key=_scan_size)
    if len(scans) < 2:
        pytest.skip('need two classifiable image scans with method files')
    full, methodless = scans[0], scans[1]

    study = tmp_path / 'study'
    study.mkdir()
    shutil.copy2(h2_study / 'subject', study / 'subject')
    shutil.copytree(h2_study / str(full), study / str(full))
    shutil.copytree(h2_study / str(methodless), study / str(methodless))
    (study / str(methodless) / 'method').unlink()   # scan now has no method file

    # sanity: the scan is registered (has reco data) but has no method entry
    d2 = BrukerLoader(str(study))
    assert methodless in d2.avail_scan_id
    assert scanMethod(d2, methodless) is None

    parent = tmp_path / 'parent'
    parent.mkdir()
    (parent / 'study').symlink_to(study.resolve())
    sheet = tmp_path / 'map'

    # bids_helper must not raise; the method-less scan is skipped.
    subprocess.check_call(['pvraw', 'bids_helper', str(parent), str(sheet)])
    listed = set(pd.read_csv(str(sheet) + '.csv')['ScanID'])
    assert methodless not in listed
    assert full in listed

    # tonii_all must not raise either.
    subprocess.check_call(['pvraw', 'tonii_all', str(parent),
                           '--output', str(tmp_path / 'nii')])


def test_software_versions_sidecar_is_string(lego_study, tmp_path):
    """SoftwareVersions is a string in the BIDS schema, but Bruker version fields
    like <6.0> parse to a float; save_json must write it as a string. We source
    it from a numeric param (the sample's own VisuAcqSoftwareVersion is absent) to
    exercise the coercion."""
    import json

    from pvraw import BrukerLoader

    d = BrukerLoader(str(lego_study))
    for sid in d.avail_scan_id:
        d.save_json(sid, 1, 'sc', dir=str(tmp_path),
                    metadata={'SoftwareVersions': 'VisuAcqRepetitionTime'})
        obj = json.loads((tmp_path / 'sc.json').read_text())
        if 'SoftwareVersions' in obj:
            assert isinstance(obj['SoftwareVersions'], str), \
                'SoftwareVersions must be a string, got {!r}'.format(obj['SoftwareVersions'])
            return
    pytest.skip('no scan with a numeric VisuAcqRepetitionTime to coerce')


def test_asl_scans_become_perf(lego_study, tmp_path):
    """FAIR/CASL scans are perf/asl, and each one gets a context file.

    They used to be forced to 'etc' because perf was unsupported. What must still
    never happen is classification by the acquisition readout: FAIR_EPI and CASL_EPI
    both contain 'epi' and would read as bold, FAIR_RARE reads as anat.

    aslcontext.tsv must have one row per volume. The validator compares it against
    the NIfTI's 4th dimension and that check IS an error -- while a *missing*
    context file silently disables eleven ASL checks, so its absence would be
    unmeasurable rather than reported.
    """
    import csv

    import nibabel as nib
    import pandas as pd

    from pvraw import BrukerLoader
    from pvraw.lib import asl as asl_lib

    sample_parent = tmp_path / 'sample'
    sample_parent.mkdir()
    (sample_parent / lego_study.name).symlink_to(lego_study.resolve())
    sheet = tmp_path / 'map'
    out = tmp_path / 'out'
    subprocess.check_call(['pvraw', 'bids_helper', str(sample_parent), str(sheet), '-j'])
    df = pd.read_csv(str(sheet) + '.csv')

    loader = BrukerLoader(str(lego_study))
    scans = [s for s in df['ScanID'].unique()
             if asl_lib.labeling_type(str(scanMethod(loader, int(s)) or ''))]
    assert scans, 'expected FAIR/CASL scans in the lego phantom'
    for s in scans:
        assigned = set(df[df['ScanID'] == s]['DataType'])
        assert assigned == {'perf'}, f'ASL scan {s} classified as {assigned}, expected perf'

    subprocess.check_call(['pvraw', 'bids_convert', str(sample_parent),
                           str(sheet) + '.csv', '-j', str(sheet) + '.json',
                           '--output', str(out)])
    contexts = list(out.rglob('*_aslcontext.tsv'))
    assert contexts, 'expected an aslcontext.tsv beside every converted ASL image'
    for context in contexts:
        rows = list(csv.DictReader(context.open(), delimiter='\t'))
        assert [r['volume_type'] for r in rows], 'context file has no rows'
        assert {r['volume_type'] for r in rows} <= {'control', 'label', 'm0scan'}
        image = context.with_name(context.name.replace('_aslcontext.tsv', '_asl.nii.gz'))
        volumes = nib.load(str(image)).shape[3]
        assert len(rows) == volumes, \
            f'{context.name}: {len(rows)} rows for {volumes} volumes'


def test_multiecho_gets_echo_entity(lego_study, tmp_path):
    """A multi-echo scan converts to one BIDS ``_echo-<n>_`` file per echo.

    Pins the BIDS naming now that image assembly is delegated to app.tonifti:
    ``is_multi_echo`` and the API's per-echo split must agree so build_bids_json
    emits ``_echo-1_``, ``_echo-2_``, ... rather than a generic ``-01`` suffix.
    """
    import types

    from pvraw import BrukerLoader
    from pvraw.lib.utils import build_bids_json

    d = BrukerLoader(str(lego_study))
    scan = next((s for s in d.avail_scan_id if d.is_multi_echo(s, 1)), None)
    if scan is None:
        pytest.skip('no multi-echo scan in sample')
    n_echo = d.is_multi_echo(scan, 1)
    row = types.SimpleNamespace(ScanID=scan, RecoID=1, task=None, DataType='anat',
                                Start=None, End=None, modality='T2starw',
                                Dir=str(tmp_path), FileName='sub-001', run=None)
    build_bids_json(d, row, 'sub-001', None)
    niis = sorted(p.name for p in tmp_path.glob('*.nii.gz'))
    assert niis == [f'sub-001_echo-{i + 1}_T2starw.nii.gz' for i in range(n_echo)]


def test_derived_reconstructions_classified_by_what_they_contain(h2_study, tmp_path):
    """A derived reconstruction is a stack, and only some of it is raw BIDS.

    An ISA fit holds one volume BIDS has a suffix for -- the relaxation time -- so
    it is labelled T1map/T2map and the converter extracts that element. Everything
    else derived (tensor stacks, unrecognised fits) stays 'etc'.

    What must never happen is the whole stack being labelled by its acquisition
    method: that produced a single-frame "MESE" with no echo-/EchoTime and a "dwi"
    whose bval/bvec length did not match the volumes.
    """
    import pandas as pd

    from pvraw import BrukerLoader
    from pvraw.lib import derived

    sample = tmp_path / 'sample'
    sample.mkdir()
    (sample / h2_study.name).symlink_to(h2_study.resolve())
    sheet = tmp_path / 'map'
    subprocess.check_call(['pvraw', 'bids_helper', str(sample), str(sheet)])
    df = pd.read_csv(str(sheet) + '.csv')

    d = BrukerLoader(str(h2_study))
    n_derived = 0
    for _, row in df.iterrows():
        scan_id, reco_id = int(row.ScanID), int(row.RecoID)
        if not derived.is_derived(d.get_frame_groups(scan_id, reco_id)):
            continue
        n_derived += 1
        found = derived.isa_map(d.get_visu_pars(scan_id, reco_id))
        if found:
            assert row.DataType == 'anat' and row.modality == found[1], \
                f'ISA map {scan_id}/{reco_id} should be anat/{found[1]}'
        else:
            assert row.DataType == 'etc', \
                f'derived reco {scan_id}/{reco_id} classified as {row.DataType}'
    assert n_derived, 'expected at least one derived (FG_ISA/FG_DTI) reconstruction'


def test_unvalidated_scans_are_kept_outside_the_validated_tree(h2_study, tmp_path):
    """A scan with no valid BIDS suffix must be kept, not dropped.

    Two destinations, because they are two different things: a ParaVision-computed
    stack with no single suffix is a derivative, while a scan we could not classify
    is source data we are declining to interpret. Both are ignored by the validator
    by definition, so nothing lands in the validated tree.
    """
    import json

    sample = tmp_path / 'sample'
    sample.mkdir()
    (sample / h2_study.name).symlink_to(h2_study.resolve())
    sheet = tmp_path / 'map'
    out = tmp_path / 'out'
    subprocess.check_call(['pvraw', 'bids_helper', str(sample), str(sheet), '-j'])
    subprocess.check_call(['pvraw', 'bids_convert', str(sample),
                           str(sheet) + '.csv', '-j', str(sheet) + '.json',
                           '--output', str(out)])

    derivatives = out / 'derivatives' / 'pvraw'
    kept = list((out / 'sourcedata').rglob('*.nii.gz')) + list(derivatives.rglob('*.nii.gz'))
    assert kept, 'expected unclassified or derived scans to be kept, not dropped'

    if list(derivatives.rglob('*.nii.gz')):
        # A derivatives directory has to stand on its own.
        desc = json.loads((derivatives / 'dataset_description.json').read_text())
        assert desc['DatasetType'] == 'derivative'
        assert desc['BIDSVersion'] == bids.BIDS_VERSION

    # Neither tree may leak into a datatype directory.
    for path in kept:
        assert 'sourcedata' in path.parts or 'derivatives' in path.parts
    for datatype in ('anat', 'func', 'dwi', 'fmap'):
        for path in out.rglob(f'sub-*/**/{datatype}/*.nii.gz'):
            assert 'sourcedata' not in path.parts and 'derivatives' not in path.parts


def test_multislicepack_uses_chunk_entity(h2_study, tmp_path):
    """A multi-slicepack reconstruction (e.g. the 0.2H2 fieldmap) must split with
    the BIDS chunk- entity plus a sidecar per chunk, not an invalid '-NN' filename
    suffix that leaves the shared sidecar orphaned."""
    import re

    sample = tmp_path / 'sample'
    sample.mkdir()
    (sample / h2_study.name).symlink_to(h2_study.resolve())
    sheet = tmp_path / 'map'
    out = tmp_path / 'out'
    subprocess.check_call(['pvraw', 'bids_helper', str(sample), str(sheet), '-j'])
    subprocess.check_call(['pvraw', 'bids_convert', str(sample),
                           str(sheet) + '.csv', '-j', str(sheet) + '.json',
                           '--output', str(out)])
    # The validated tree only: sourcedata/ and derivatives/ are outside BIDS
    # filename rules, and their chunk-NN spelling is not what this guards against.
    niis = [p for p in out.rglob('*.nii.gz')
            if 'sourcedata' not in p.parts and 'derivatives' not in p.parts]
    bad = [p.name for p in niis if re.search(r'(?<!chunk)-\d{2}\.nii\.gz$', p.name)]
    assert not bad, f'invalid -NN split filenames: {bad}'
    chunked = [p for p in niis if '_chunk-' in p.name]
    assert chunked, 'expected chunk- split outputs (0.2H2 fieldmap)'
    for p in chunked:
        if '_magnitude' not in p.name:   # magnitude needs no sidecar
            assert p.with_name(p.name.replace('.nii.gz', '.json')).exists(), \
                f'orphaned/missing sidecar for {p.name}'


def test_single_echo_msme_is_t2w_not_mese(h2_study, tmp_path):
    """A single-echo MSME is a T2-weighted image, not a BIDS MESE (which requires
    an echo- entity). bids_helper must give it the T2w suffix, not MESE. Built by
    relabelling a single-echo image scan's method as MSME (no online fixture ships
    a single-echo MSME)."""
    import re
    import shutil

    import pandas as pd

    from pvraw import BrukerLoader
    from pvraw.scripts.pvraw import is_localizer

    d = BrukerLoader(str(h2_study))
    scan = next((s for s in d.avail_scan_id
                 if (h2_study / str(s) / 'method').is_file()
                 and not d.is_multi_echo(s, 1)
                 and d._get_dim_info(d._get_visu_pars(s, 1))[1] == 'spatial_only'
                 and not is_localizer(d, s, 1)), None)
    if scan is None:
        pytest.skip('no single-echo image scan with a method file')

    study = tmp_path / 'study'
    study.mkdir()
    shutil.copy2(h2_study / 'subject', study / 'subject')
    shutil.copytree(h2_study / str(scan), study / str(scan))
    mpath = study / str(scan) / 'method'
    mpath.write_text(re.sub(r'##\$Method=.*', '##$Method=MSME', mpath.read_text(), count=1))

    parent = tmp_path / 'parent'
    parent.mkdir()
    (parent / 'study').symlink_to(study.resolve())
    sheet = tmp_path / 'map'
    subprocess.check_call(['pvraw', 'bids_helper', str(parent), str(sheet)])
    df = pd.read_csv(str(sheet) + '.csv')
    row = df[df['ScanID'] == scan]
    assert not row.empty and row.iloc[0]['modality'] == 'T2w', \
        'single-echo MSME should be T2w, got {}'.format(
            None if row.empty else row.iloc[0]['modality'])


def test_dwi_bval_tiled_to_volume_count(h2_study, tmp_path):
    """A multi-cycle/repetition DWI keeps every repeat as a separate volume; the
    per-direction bval/bvec must be tiled to one entry per volume (else BIDS
    VOLUME_COUNT_MISMATCH). The diffusion block repeats per cycle, so the tile is
    block-wise, not element-wise."""
    import numpy as np

    from pvraw import BrukerLoader

    d = BrukerLoader(str(h2_study))
    scan = next((s for s in d.avail_scan_id
                 if d.get_method(s) is not None
                 and 'PVM_DwEffBval' in d.get_method(s)), None)
    if scan is None:
        pytest.skip('no diffusion scan in sample')
    bvals0, _ = d._get_bdata(d.get_method(scan))
    n = len(np.atleast_1d(bvals0))
    d.save_bdata(scan, 'sc', dir=str(tmp_path), reco_id=1, num_volumes=3 * n)
    bval = tmp_path.joinpath('sc.bval').read_text().split()
    assert len(bval) == 3 * n
    assert bval[:n] == bval[n:2 * n] == bval[2 * n:3 * n]   # block-tiled, not repeated
