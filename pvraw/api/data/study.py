"""Study-level container for a PvDataset.

This is where pvraw's vocabulary meets `brukerapi`'s: a Scan is a
`brukerapi` ``Experiment`` and a Reco is a ``Processing`` (see ``CONTEXT.md``).
Those two type names are the whole of the translation -- nothing anywhere
speaks ``exp_id``/``proc_id``, and every method and identifier here is
``scan_id``/``reco_id``.

Reading -- directory walking, archive access, JCAMP-DX parsing and binary
assembly -- belongs to `brukerapi` (ADR 0002). What survives here is the
translation of a user-supplied path into the scans and reconstructions the rest
of pvraw addresses by ``scan_id``/``reco_id``.
"""

from __future__ import annotations

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
from brukerapi.folders import Study as BrukerapiStudy
from brukerapi.jcampdx import JCAMPDX
from reshipe import RecipeParser

from pvraw.api.analyzer.base import BaseAnalyzer
from pvraw.lib.errors import FileNotValidError
from pvraw.lib.utils import get_value

from .scan import Scan

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


def _archive_root(path: Path):
    """The study directory inside an archive, as a ``zipfile.Path``.

    A PvDataset archive wraps the study in a single top-level directory (a
    ``.PvDatasets`` export adds a sibling ``.examination`` file). `brukerapi`
    reads through the pathlib protocol, so the member path is handed over
    directly rather than extracting the archive.
    """
    root = zipfile.Path(zipfile.ZipFile(path))
    directories = [child for child in root.iterdir() if child.is_dir()]
    if len(directories) != 1:
        raise FileNotValidError(str(path), 'PvDataset archive')
    return directories[0]


def _open_container(path: Path):
    """Open `path` as a `brukerapi` folder.

    A study is recognised by its ``subject`` file and an individually exported
    scan by an ``acqp`` at its root. Anything else is a plain ``Folder``, whose
    numbered scan directories -- a partial export omits the ``subject`` file --
    are what ``_scan_index`` addresses; a directory that is no PvDataset at all
    simply indexes no scans. An archive takes the same fallbacks as the
    directory it extracts to: the two forms are the same PvDataset, so which
    one the user hands over must not change what converts (issue #62 -- the
    directory branch used to reject the partial exports the archive branch
    accepted).
    """
    if not path.exists():
        raise FileNotValidError(str(path), 'PvDataset')

    if path.is_file():
        if not zipfile.is_zipfile(path):
            raise FileNotValidError(str(path), 'PvDataset')
        path = _archive_root(path)

    try:
        return BrukerapiStudy(path, dataset_state=UNLOADED)
    except NotStudyFolder:
        pass
    try:
        return Experiment(path, dataset_state=UNLOADED)
    except NotExperimentFolder:
        return Folder(path, dataset_state=UNLOADED)


def _scan_index(container) -> dict:
    """Map ``scan_id`` to the `brukerapi` Experiment holding that scan.

    Scans are the numbered directories directly under the study -- nested
    studies are separate PvDatasets and are not folded in here. An individually
    exported scan is its own container and is addressed as scan 1.
    """
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

    def _load_subject(self) -> JCAMPDX | None:
        """The study-level ``subject`` file, or None when the export omits it."""
        if isinstance(self._container, Experiment):
            return None
        subject = self._container.path / 'subject'
        if not subject.exists():
            return None
        try:
            return JCAMPDX(subject)
        except Exception as error:
            warnings.warn(f'Could not read the subject file ({error}); subject-derived '
                          'fields are unavailable.', UserWarning)
            return None

    @property
    def pvobj(self):
        """The `brukerapi` folder this study reads through."""
        return self._container

    @property
    def path(self) -> Path:
        return self._path

    @property
    def subject(self) -> JCAMPDX | None:
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

    def get_scan(self, scan_id: int, reco_id: int | None = None,
                 debug: bool = False) -> Scan:
        """The Scan for `scan_id`, optionally bound to one reconstruction."""
        return Scan(self._scans[scan_id], reco_id=reco_id, debug=debug)

    def _parse_header(self) -> None:
        """Subject-level parameters, keyed without their ``SUBJECT_`` prefix."""
        self.header = None
        if self._subject is None:
            return
        self.header = {key.replace('SUBJECT_', ''): get_value(self._subject, key)
                       for key in self._subject if key.startswith('SUBJECT')}
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
        """Compile study, scan and reconstruction headers via the study recipe.

        Every recipe key is present in every header, absent values as None, so
        the shape downstream consumers (``BrukerLoader.info_dict``) see does not
        depend on which parameters a ParaVision version writes. A scan or
        reconstruction that cannot be analysed is kept as an entry whose header
        carries only ``error`` -- listing a study must not abort because one
        scan of it is unreadable.
        """
        spec_path = os.path.join(os.path.dirname(__file__), 'study.yaml')
        with open(spec_path, 'r') as f:
            spec = yaml.safe_load(f)

        def parse(targets, level):
            parsed = RecipeParser(targets, copy(spec)[level]).get()
            return {key: parsed.get(key) for key in spec[level]}

        self._info = StudyHeader(header=parse(self, 'study'), scans=[])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for scan_id in self.avail:
                try:
                    scan_header = self._scan_header(scan_id, parse)
                except Exception as error:
                    scan_header = ScanHeader(scan_id=scan_id,
                                             header={'error': str(error)}, recos=[])
                self._info.scans.append(scan_header)

    def _scan_header(self, scan_id, parse):
        """One scan's header and reco headers; reco failures stay per-reco."""
        scanobj = self.get_scan(scan_id)
        scan_header = ScanHeader(scan_id=scan_id,
                                 header=parse(scanobj.info, 'scan'),
                                 recos=[])
        for reco_id in scanobj.avail:
            try:
                recoinfo = scanobj.get_scaninfo(reco_id=reco_id)
                header = parse([recoinfo], 'reco')
                header['warns'] = list(recoinfo.warns)
            except Exception as error:
                header = {'error': str(error)}
            scan_header.recos.append(RecoHeader(reco_id=reco_id, header=header))
        return scan_header
