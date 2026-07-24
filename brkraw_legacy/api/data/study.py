"""Study-level container for a PvDataset.

This is where brkraw-legacy's vocabulary meets `brukerapi`'s: a Scan is a
`brukerapi` ``Experiment`` and a Reco is a ``Processing`` (see ``CONTEXT.md``).
Those two type names are the whole of the translation -- nothing anywhere
speaks ``exp_id``/``proc_id``, and every method and identifier here is
``scan_id``/``reco_id``.

Reading -- directory walking, archive access, JCAMP-DX parsing and binary
assembly -- belongs to `brukerapi` (ADR 0002). What survives here is the
translation of a user-supplied path into the scans and reconstructions the rest
of brkraw-legacy addresses by ``scan_id``/``reco_id``.
"""

from __future__ import annotations

import importlib.util
import os
import warnings
import zipfile
from copy import copy
from dataclasses import dataclass
from pathlib import Path

import yaml
from brukerapi.dataset import LOAD_STAGES
from brukerapi.exceptions import NotExperimentFolder, NotStudyFolder
from brukerapi.folders import Experiment, Folder
from brukerapi.folders import Study as PvStudy
from brukerapi.jcampdx import JCAMPDX
from reshipe import RecipeParser

from brkraw_legacy.api.analyzer.base import BaseAnalyzer
from brkraw_legacy.lib.errors import FileNotValidError, InvalidApproach
from brkraw_legacy.lib.utils import get_value

from .scan import Scan

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Optional


#: Walking the tree must not read image data: a study is opened to list its
#: scans, and the 2dseq of every reconstruction is megabytes.
UNLOADED = {'load': LOAD_STAGES['empty']}


@dataclass
class StudyHeader:
    header: dict
    scans: list


@dataclass
class ScanHeader:
    scan_id: int
    header: dict
    recos: list


@dataclass
class RecoHeader:
    reco_id: int
    header: dict


def _require_archive_support():
    """Fail with the reason when the installed `brukerapi` is path-only.

    Archives are read in place, which needs the pathlib read protocol
    `brukerapi` gained in 0.4. An older release coerces every path with
    ``Path()`` and dies on a ``zipfile.Path`` with a TypeError about os.PathLike
    -- which reads like a corrupt dataset rather than a dependency to upgrade.
    """
    if not importlib.util.find_spec('brukerapi.paths'):
        raise InvalidApproach(
            'Reading a .zip/.PvDatasets archive needs brukerapi>=0.4 (the '
            'pathlib path protocol); the installed version can only read a '
            'directory. Upgrade brukerapi, or extract the archive first.')


def _archive_root(path: Path):
    """The study directory inside an archive, as a ``zipfile.Path``.

    A PvDataset archive wraps the study in a single top-level directory (a
    ``.PvDatasets`` export adds a sibling ``.examination`` file). `brukerapi`
    reads through the pathlib protocol, so the member path is handed over
    directly rather than extracting the archive.
    """
    _require_archive_support()
    root = zipfile.Path(zipfile.ZipFile(path))
    directories = [child for child in root.iterdir() if child.is_dir()]
    if len(directories) != 1:
        raise FileNotValidError(str(path), 'PvDataset archive')
    return directories[0]


def _open_container(path: Path):
    """Open `path` as a `brukerapi` folder, or return None if it is no PvDataset.

    A study is recognised by its ``subject`` file and an individually exported
    scan by an ``acqp`` at its root -- a directory holding neither is a
    collection of datasets, not one dataset, and yields no scans. Inside an
    archive the ``subject`` file is optional: partial exports omit it and are
    still addressed by their numbered scan directories.
    """
    if not path.exists():
        raise FileNotValidError(str(path), 'PvDataset')

    if path.is_file():
        if not zipfile.is_zipfile(path):
            raise FileNotValidError(str(path), 'PvDataset')
        root = _archive_root(path)
        try:
            return PvStudy(root, dataset_state=UNLOADED)
        except NotStudyFolder:
            return Folder(root, dataset_state=UNLOADED)

    try:
        return PvStudy(path, dataset_state=UNLOADED)
    except NotStudyFolder:
        pass
    try:
        return Experiment(path, dataset_state=UNLOADED)
    except NotExperimentFolder:
        return None


def _scan_index(container) -> dict:
    """Map ``scan_id`` to the `brukerapi` Experiment holding that scan.

    Scans are the numbered directories directly under the study -- nested
    studies are separate PvDatasets and are not folded in here. An individually
    exported scan is its own container and is addressed as scan 1.
    """
    if container is None:
        return {}
    if isinstance(container, Experiment):
        return {1: container}
    scans = {}
    for child in container.children:
        if not (isinstance(child, Folder) and child.path.name.isdigit()):
            continue
        # An Experiment, or -- for a scan exported without its acqp, which is
        # what makes a folder an Experiment -- any numbered folder that still
        # holds a reconstruction. Such a scan converts; only the acquisition
        # protocol is unavailable.
        if isinstance(child, Experiment) or child.get_processing_list():
            scans[int(child.path.name)] = child
    return scans


class Study(BaseAnalyzer):
    """One PvDataset: a subject-session supplied as a directory or an archive.

    Attributes:
        header (Optional[dict]): Subject-level parameters, or None without a
            ``subject`` file (an individually exported scan has none).
    """
    _info: StudyHeader

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._container = _open_container(self._path)
        self._scans = _scan_index(self._container)
        self._subject = self._load_subject()
        self._parse_header()

    def _load_subject(self) -> Optional[JCAMPDX]:
        """The study-level ``subject`` file, or None when the export omits it."""
        if self._container is None or isinstance(self._container, Experiment):
            return None
        subject = self._container.path / 'subject'
        if not subject.exists():
            return None
        try:
            return JCAMPDX(subject)
        except Exception as error:  # noqa: BLE001
            warnings.warn('Could not read the subject file ({}); subject-derived '
                          'fields are unavailable.'.format(error), UserWarning)
            return None

    @property
    def pvobj(self):
        """The `brukerapi` folder this study reads through."""
        return self._container

    @property
    def path(self) -> Path:
        return self._path

    @property
    def subject(self) -> Optional[JCAMPDX]:
        return self._subject

    @property
    def avail(self) -> list:
        """Available ``scan_id``s, ascending."""
        return sorted(self._scans)

    @property
    def avail_reco_id(self) -> dict:
        """``{scan_id: [reco_id, ...]}`` for every scan holding a reconstruction.

        Built from plain Scans so that listing a study does not reject the
        scans it cannot convert: a spectroscopic scan is still addressable, and
        is skipped with a clear message when conversion is attempted.
        """
        avail = {}
        for scan_id, experiment in sorted(self._scans.items()):
            if recos := Scan(experiment).avail:
                avail[scan_id] = recos
        return avail

    def get_pvscan(self, scan_id: int):
        """The `brukerapi` Experiment for `scan_id`."""
        return self._scans[scan_id]

    def get_scan(self, scan_id: int, reco_id: Optional[int] = None,
                 debug: bool = False) -> 'Scan':
        """The Scan for `scan_id`, optionally bound to one reconstruction."""
        return Scan(self._scans[scan_id], reco_id=reco_id, debug=debug)

    def _parse_header(self) -> None:
        """Subject-level parameters, keyed without their ``SUBJECT_`` prefix."""
        self.header = None
        if self._subject is None:
            return
        self.header = {key.replace('SUBJECT_', ''): get_value(self._subject, key)
                       for key in self._subject.keys() if key.startswith('SUBJECT')}
        title = get_value(self._subject, 'TITLE')
        self.header['sw_version'] = (str(title).split(',')[-1].strip()
                                     if title and 'ParaVision' in str(title)
                                     else 'ParaVision < 6')
        self.header['study_operator'] = get_value(self._subject, 'OWNER')

    @property
    def info(self) -> dict:
        if not hasattr(self, '_info'):
            self._process_header()
        if not hasattr(self, '_streamed_info'):
            self._streamed_info = self._stream_info()
        return self._streamed_info

    def _stream_info(self):
        stream = copy(self._info.__dict__)
        scans = {}
        for s in self._info.scans:
            scans[s.scan_id] = s.header
            recos = {}
            for r in s.recos:
                recos[r.reco_id] = r.header
            if recos:
                scans[s.scan_id]['recos'] = recos
        stream['scans'] = scans
        return stream

    def _process_header(self):
        """Compile study, scan and reconstruction headers via the study recipe."""
        spec_path = os.path.join(os.path.dirname(__file__), 'study.yaml')
        with open(spec_path, 'r') as f:
            spec = yaml.safe_load(f)
        self._info = StudyHeader(header=RecipeParser(self, copy(spec)['study']).get(),
                                 scans=[])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for scan_id in self.avail:
                scanobj = self.get_scan(scan_id)
                scan_spec = copy(spec)['scan']
                scaninfo_targets = scanobj.info
                scan_header = ScanHeader(scan_id=scan_id,
                                         header=RecipeParser(scaninfo_targets, scan_spec).get(),
                                         recos=[])
                for reco_id in scanobj.avail:
                    recoinfo_targets = [scanobj.get_scaninfo(reco_id=reco_id)]
                    reco_spec = copy(spec)['reco']
                    parsed_reco = RecipeParser(recoinfo_targets, reco_spec).get()
                    reco_header = RecoHeader(reco_id=reco_id,
                                             header=parsed_reco) if parsed_reco else None
                    if reco_header:
                        scan_header.recos.append(reco_header)
                self._info.scans.append(scan_header)
