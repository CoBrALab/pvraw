"""BIDS path-builder and end-to-end conversion tests.

The unit tests exercise ``brkraw_legacy.lib.bids`` directly and need no sample
data. The end-to-end tests convert a public sample study (lego_phantom); the
validator check is skipped unless the ``bids-validator`` (Deno) binary is
available.
"""
import json
import shutil
import subprocess

import pytest

from brkraw_legacy.lib import bids
from brkraw_legacy.lib.errors import InvalidApproach
from brkraw_legacy.scripts.brkraw_legacy import scanMethod

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

    from brkraw_legacy.lib.reference import DATASET_DESC_REF

    assert re.fullmatch(r'\d+\.\d+\.\d+', bids.BIDS_VERSION), bids.BIDS_VERSION
    # The template must not carry a version of its own to drift from the schema.
    assert DATASET_DESC_REF['BIDSVersion'] == ''


def test_subject_session_id_sanitized_to_valid_bids_label():
    """A subject/session ID must become an alphanumeric BIDS label. Regression:
    a version-derived id like PV360's ``std_PV360_3.7`` kept its '.', which is
    invalid in a sub-<label> and made the whole subject tree unrecognizable."""
    import re
    import warnings

    from brkraw_legacy.scripts.brkraw_legacy import cleanSessionID, cleanSubjectID

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


def _prepare_anat_dataset(pvdir, tmp_path):
    """Run bids_helper, fill in a couple of valid anat rows, and convert.

    The sample scans have no auto-classifiable BIDS datatype, so we rewrite two
    single-volume 3D scans as anat/T2starw to exercise a real, validatable
    conversion (multi-slicepack scouts would split into several files and are
    skipped). Only the chosen study is exposed (via a symlinked parent) so the
    helper converts just it.
    """
    import pandas as pd

    from brkraw_legacy import BrukerLoader

    # Pick scans that convert to a single 3D image, so each yields one clean
    # anat file rather than a per-slicepack _T2starw-01/-02/... split.
    loader = BrukerLoader(str(pvdir))
    simple = []
    for sid in loader.avail_scan_id:
        try:
            obj = loader.get_niftiobj(sid, 1)
        except Exception:
            continue
        if not isinstance(obj, list) and getattr(obj, 'ndim', 0) == 3:
            simple.append(sid)
        if len(simple) >= 2:
            break
    assert simple, 'no single-volume 3D scan available for anat conversion'

    sample_parent = tmp_path / 'sample'
    sample_parent.mkdir()
    (sample_parent / pvdir.name).symlink_to(pvdir.resolve())
    sheet = tmp_path / 'bids_map'
    out = tmp_path / 'raw'

    subprocess.check_call(['brkraw-legacy', 'bids_helper', str(sample_parent),
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

    subprocess.check_call(['brkraw-legacy', 'bids_convert', str(sample_parent),
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
    assert any(g['Name'] == 'BrkRaw-legacy' for g in desc['GeneratedBy'])
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


def test_phase_encoding_direction_is_bids_axis(h2_study, tmp_path):
    """Every emitted PhaseEncodingDirection must be a BIDS axis (i/j/k[-]), not a
    raw Bruker code. Regression: PV5.1's uniform ``VisuAcqImagePhaseEncDir`` of
    ``col_dir`` reached the sidecar verbatim (schema-invalid)."""
    valid = {'i', 'i-', 'j', 'j-', 'k', 'k-'}
    sample = tmp_path / 'sample'
    sample.mkdir()
    (sample / h2_study.name).symlink_to(h2_study.resolve())
    sheet = tmp_path / 'map'
    out = tmp_path / 'out'
    subprocess.check_call(['brkraw-legacy', 'bids_helper', str(sample), str(sheet), '-j'])
    subprocess.check_call(['brkraw-legacy', 'bids_convert', str(sample),
                           str(sheet) + '.csv', '-j', str(sheet) + '.json',
                           '--output', str(out)])
    seen = 0
    for js in out.rglob('*.json'):
        pe = json.loads(js.read_text()).get('PhaseEncodingDirection')
        if pe is not None:
            assert pe in valid, f'{js.name}: {pe!r}'
            seen += 1
    if not seen:
        pytest.skip('no PhaseEncodingDirection emitted in this sample')


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
    from brkraw_legacy import BrukerLoader

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
    subprocess.check_call(['brkraw-legacy', 'bids_helper', str(sample), str(sheet), '-j'])

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
    result = subprocess.run(['brkraw-legacy', 'bids_convert', str(sample),
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

    from brkraw_legacy import BrukerLoader
    from brkraw_legacy.scripts.brkraw_legacy import is_localizer

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
    subprocess.check_call(['brkraw-legacy', 'bids_helper', str(parent), str(sheet)])
    listed = set(pd.read_csv(str(sheet) + '.csv')['ScanID'])
    assert methodless not in listed
    assert full in listed

    # tonii_all must not raise either.
    subprocess.check_call(['brkraw-legacy', 'tonii_all', str(parent),
                           '--output', str(tmp_path / 'nii')])


def test_software_versions_sidecar_is_string(lego_study, tmp_path):
    """SoftwareVersions is a string in the BIDS schema, but Bruker version fields
    like <6.0> parse to a float; save_json must write it as a string. We source
    it from a numeric param (the sample's own VisuAcqSoftwareVersion is absent) to
    exercise the coercion."""
    import json

    from brkraw_legacy import BrukerLoader

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


def test_asl_scans_not_auto_classified(lego_study, tmp_path):
    """FAIR/CASL/perfusion scans must not be auto-classified as bold or anat (BIDS
    perf/asl is unsupported here); the helper leaves them as 'etc' for the user."""
    import re

    import pandas as pd

    from brkraw_legacy import BrukerLoader

    sample_parent = tmp_path / 'sample'
    sample_parent.mkdir()
    (sample_parent / lego_study.name).symlink_to(lego_study.resolve())
    sheet = tmp_path / 'map'
    subprocess.check_call(['brkraw-legacy', 'bids_helper', str(sample_parent), str(sheet)])
    df = pd.read_csv(str(sheet) + '.csv')

    loader = BrukerLoader(str(lego_study))
    asl = [s for s in df['ScanID'].unique()
           if re.search(r'FAIR|ASL|perfusion',
                        str(scanMethod(loader, int(s)) or ''),
                        re.IGNORECASE)]
    assert asl, 'expected FAIR/CASL scans in the lego phantom'
    for s in asl:
        assigned = set(df[df['ScanID'] == s]['DataType'])
        assert assigned == {'etc'}, \
            f'ASL scan {s} classified as {assigned}, expected etc'


def test_multiecho_gets_echo_entity(lego_study, tmp_path):
    """A multi-echo scan converts to one BIDS ``_echo-<n>_`` file per echo.

    Pins the BIDS naming now that image assembly is delegated to app.tonifti:
    ``is_multi_echo`` and the API's per-echo split must agree so build_bids_json
    emits ``_echo-1_``, ``_echo-2_``, ... rather than a generic ``-01`` suffix.
    """
    import types

    from brkraw_legacy import BrukerLoader
    from brkraw_legacy.lib.utils import build_bids_json

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


def test_derived_reconstructions_not_auto_classified(h2_study, tmp_path):
    """ISA parametric maps and generated DTI tensor images are BIDS derivatives;
    bids_helper must leave them 'etc', not label them anat/MESE or dwi -- which
    produced a single-frame "MESE" with no echo-/EchoTime and a "dwi" whose
    bval/bvec length did not match the volumes."""
    import pandas as pd

    from brkraw_legacy import BrukerLoader

    sample = tmp_path / 'sample'
    sample.mkdir()
    (sample / h2_study.name).symlink_to(h2_study.resolve())
    sheet = tmp_path / 'map'
    subprocess.check_call(['brkraw-legacy', 'bids_helper', str(sample), str(sheet)])
    df = pd.read_csv(str(sheet) + '.csv')

    d = BrukerLoader(str(h2_study))
    n_derived = 0
    for _, row in df.iterrows():
        groups = [name for name, _ in d.get_frame_groups(int(row.ScanID), int(row.RecoID))]
        if any(g in ('isa', 'dti') for g in groups):
            n_derived += 1
            assert row.DataType == 'etc', \
                f'derived reco {row.ScanID}/{row.RecoID} classified as {row.DataType}'
    assert n_derived, 'expected at least one derived (FG_ISA/FG_DTI) reconstruction'


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
    subprocess.check_call(['brkraw-legacy', 'bids_helper', str(sample), str(sheet), '-j'])
    subprocess.check_call(['brkraw-legacy', 'bids_convert', str(sample),
                           str(sheet) + '.csv', '-j', str(sheet) + '.json',
                           '--output', str(out)])
    niis = list(out.rglob('*.nii.gz'))
    bad = [p.name for p in niis if re.search(r'-\d{2}\.nii\.gz$', p.name)]
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

    from brkraw_legacy import BrukerLoader
    from brkraw_legacy.scripts.brkraw_legacy import is_localizer

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
    subprocess.check_call(['brkraw-legacy', 'bids_helper', str(parent), str(sheet)])
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

    from brkraw_legacy import BrukerLoader

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
