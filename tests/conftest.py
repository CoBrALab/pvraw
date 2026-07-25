"""Shared pytest fixtures.

All sample data is fetched from public online sources -- never from local
files -- so the suite is reproducible on any checkout:

* 0.2H2 (PV5.1, 32 exp)          -- zenodo.org/records/4048286
* lego_phantom (PV6.0.1, 45 exp) -- zenodo.org/records/4048253
* PV7.0.0 LEGO_PHANTOM_API_TEST  -- zenodo.org/records/4522220
* PV360 v3.6 std data            -- github.com/cecilyen/PV360_StdData

Datasets are cached under ``$BRKRAW_TEST_DATA_DIR`` (default: a temp dir) so a
CI job can restore them from cache and skip re-downloading. A dataset that
cannot be fetched (no network, server error) makes its dependent tests *skip*,
never error. Any test that requests one of these fixtures is auto-tagged with
the ``data`` marker, so ``pytest -m "not data"`` runs the pure-unit suite with
no downloads.
"""
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

import pytest

from brkraw_legacy import setup_logging
from brkraw_legacy.api.data import Study


def pytest_configure(config):
    setup_logging(path=Path(__file__).parent / 'logging.yaml')


#: Tests requesting any of these fixtures are network-bound; auto-mark them.
_DATA_FIXTURES = {'dataset', 'h2_study', 'lego_study', 'pv360_root', 'pv7_study'}


@pytest.hookimpl(tryfirst=True)  # add marks before -m deselection runs
def pytest_collection_modifyitems(config, items):
    for item in items:
        if _DATA_FIXTURES.intersection(getattr(item, 'fixturenames', ())):
            item.add_marker(pytest.mark.data)


# --------------------------------------------------------------------------- #
# Online sample-data cache
# --------------------------------------------------------------------------- #

def _data_dir():
    root = os.environ.get('BRKRAW_TEST_DATA_DIR')
    root = Path(root) if root else Path(tempfile.gettempdir()) / 'brkraw_legacy_test_data'
    root.mkdir(parents=True, exist_ok=True)
    return root


def _find_study_root(top):
    """The directory holding a Bruker ``subject`` file (a study root)."""
    if (top / 'subject').is_file():
        return top
    for sub in sorted(top.rglob('subject')):
        if sub.is_file():
            return sub.parent
    return None


def _fetch_zenodo_study(record_id, filename):
    """Download+extract a Zenodo zip once; return the study root, or None."""
    dest = _data_dir() / 'zenodo-{}'.format(record_id)
    if dest.exists():
        return _find_study_root(dest)
    tmp_zip = _data_dir() / filename
    tmp_dir = _data_dir() / 'zenodo-{}.partial'.format(record_id)
    url = 'https://zenodo.org/records/{}/files/{}?download=1'.format(record_id, filename)
    try:
        with urlopen(url, timeout=60) as resp, open(tmp_zip, 'wb') as fh:
            shutil.copyfileobj(resp, fh)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True)
        with zipfile.ZipFile(tmp_zip) as zf:
            zf.extractall(tmp_dir)
        tmp_dir.rename(dest)                    # publish atomically on success
    except Exception:                          # network / server / bad zip
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None
    finally:
        tmp_zip.unlink(missing_ok=True)
    return _find_study_root(dest)


def _clone(url, name, lfs_include=None):
    """Clone a git repo once into the cache; return its path, or None.

    LFS objects are pulled after a smudge-skipped clone so an ``lfs_include``
    can restrict the (potentially large) download to just what a test needs.
    Missing git-lfs is tolerated: pointers are left in place and the size-check
    guards in the tests skip the affected cases.
    """
    dest = _data_dir() / name
    if dest.exists():
        return dest
    tmp = _data_dir() / (name + '.partial')
    shutil.rmtree(tmp, ignore_errors=True)
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE='1')
    try:
        subprocess.check_call(['git', 'clone', '--depth', '1', url, str(tmp)], env=env)
        pull = ['git', '-C', str(tmp), 'lfs', 'pull']
        if lfs_include:
            pull += ['--include', lfs_include]
        subprocess.call(pull)                  # best-effort; no-op without git-lfs
        tmp.rename(dest)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    return dest


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope='session')
def h2_study():
    """PV5.1 multi-sequence phantom study (Zenodo 4048286, 32 experiments)."""
    root = _fetch_zenodo_study(4048286, '0.2H2.zip')
    if root is None:
        pytest.skip('0.2H2 (Zenodo 4048286) unavailable')
    return root


@pytest.fixture(scope='session')
def lego_study():
    """PV6.0.1 multi-sequence phantom study (Zenodo 4048253, 45 experiments)."""
    root = _fetch_zenodo_study(4048253, '20200612_094625_lego_phantom_3_1_2.zip')
    if root is None:
        pytest.skip('lego_phantom (Zenodo 4048253) unavailable')
    return root


@pytest.fixture(scope='session')
def pv7_study():
    """PV7.0.0 multi-sequence phantom study (Zenodo 4522220, LEGO_PHANTOM_API_TEST)."""
    root = _fetch_zenodo_study(4522220, '20210128_122257_LEGO_PHANTOM_API_TEST_1_1.zip')
    if root is None:
        pytest.skip('PV7 LEGO_PHANTOM (Zenodo 4522220) unavailable')
    return root


@pytest.fixture(scope='session')
def pv360_root():
    """PV360 v3.6 standard phantom: a collection of loose scan dirs (no subject)."""
    root = _clone('https://github.com/cecilyen/PV360_StdData.git',
                  'PV360_StdData', lfs_include='T1_FLASH/**')
    if root is None:
        pytest.skip('PV360_StdData clone unavailable')
    return root


@pytest.fixture(scope='session')
def dataset(h2_study, lego_study, pv7_study):
    """Proper multi-scan studies keyed by index (0.2H2 PV5.1, lego_phantom PV6.0.1,
    LEGO_PHANTOM_API_TEST PV7.0.0)."""
    return {0: Study(h2_study), 1: Study(lego_study), 2: Study(pv7_study)}
