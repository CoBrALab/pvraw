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

import warnings
import zipfile
from copy import copy
from dataclasses import dataclass
from pathlib import Path

from brukerapi.dataset import LOAD_STAGES
from brukerapi.exceptions import NotExperimentFolder, NotStudyFolder
from brukerapi.folders import Experiment, Folder
from brukerapi.folders import Study as BrukerapiStudy
from brukerapi.jcampdx import JCAMPDX

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


#: The three header recipes: output key -> where the value comes from, as a
#: ``'section.key'`` path on the parse target, or a tuple of paths taking the
#: first that resolves. The keys are the public vocabulary of
#: ``BrukerLoader.info_dict()`` -- renaming one is a breaking change for
#: `--json` consumers. Units are baked into the key names (`_ms`, `_mm`, ...)
#: because every unit ParaVision writes here is a constant.
#:
#: Formerly a reshipe recipe (study.yaml). reshipe returned a spec string that
#: matched no target verbatim -- which is how ``operator`` was once the
#: literal string ``'study_operator'`` -- and its ``script:`` case stopped
#: working on Python >= 3.13 (PEP 667), so what survives here is the two
#: features the recipes actually used.
#: Subject-file keys are the PV5.1/PV6 spellings with PV360's renamings as the
#: first candidate (FILE_FORMAT.md section 9). The names say whose attribute
#: each is -- ``subject_name`` is the subject's, not a researcher's.
_STUDY_RECIPE = {
    # who ran it
    'user_account': 'header.owner',                              # ##OWNER: the login
    'operator': ('header.study_operator', 'header.referral'),    # the person entered at registration
    # the subject (SUBJECT_object)
    'subject_id': 'header.id',
    'subject_name': 'header.name_string',
    'subject_uid': ('header.instance_uid', 'header.patient_instance_uid'),
    'subject_type': 'header.type',
    'dob': 'header.dbirth',
    'sex': ('header.gender', 'header.sex'),
    'weight': ('header.study_weight', 'header.weight'),
    'remarks': 'header.remarks',
    # the study (SUBJECT_study)
    'study_name': 'header.study_name',
    'study_nr': 'header.study_nr',
    'study_uid': 'header.study_instance_uid',
    'date': ('header.study_date', 'header.date'),
    'purpose': 'header.purpose',
    'study_comment': ('header.study_comment', 'header.comment'),
    'modalities': 'header.study_modalities',
    'use_ats': 'header.study_use_ats',                           # CMN_study_use_ats (PV360)
    'animal_bed': 'header.study_bed',                            # CMN_study_bed (PV360)
    'sw_version': 'header.sw_version',
    # `position` is deliberately absent: PV360's single parameter and the
    # older entry/position split are resolved by BrukerLoader._study_block.
}

_SCAN_RECIPE = {
    'method': 'protocol.scan_method',
    'protocol': 'protocol.protocol_name',
    'ppg': 'protocol.pulse_program',
    'nucleus': 'protocol.nucleus',
    'institution': 'protocol.institution',
    'station': 'protocol.device',
    'scan_name': 'seqparams.scan_name',
    'sequence': 'seqparams.sequence_name',
    'acq_date': 'seqparams.acq_date',
    'tr_ms': 'seqparams.repetition_time',
    'te_ms': 'seqparams.echo_time',
    'ti_ms': 'seqparams.inversion_time',
    'flip_angle_deg': 'seqparams.flip_angle',
    'pixel_bandwidth_hz': 'seqparams.pixel_bandwidth',
    'num_averages': 'seqparams.num_averages',
    'num_repetitions': 'seqparams.num_repetitions',
    'echo_train_length': 'seqparams.echo_train_length',
    'imaging_frequency_mhz': 'seqparams.imaging_frequency',
}

_RECO_RECIPE = {
    'dim': 'image.dim',
    'fov_mm': 'image.field_of_view',
    'resolution_mm': 'image.resolution',
    'num_slice_packs': 'slicepack.num_slice_packs',
    'num_slices_each_pack': 'slicepack.num_slices_each_pack',
    'slice_distances_mm': 'slicepack.slice_distances_each_pack',
    'slice_order_scheme': 'slicepack.slice_order_scheme',
    'num_cycles': 'cycle.num_cycles',
    'time_step_ms': 'cycle.time_step',
    'scan_time_ms': 'cycle.scan_time',
    'axis_labels': 'dataarray.axis_labels',
}


def _resolve(target, path):
    """One recipe value: ``'section.key'`` looked up on `target`, or a tuple
    of such paths taking the first that resolves.

    None when nothing resolves -- never a literal string. A single target on
    purpose: reshipe's multi-target search was never used with more than one.
    """
    if isinstance(path, (tuple, list)):
        for candidate in path:
            value = _resolve(target, candidate)
            if value is not None:
                return value
        return None
    section_name, _, key = path.partition('.')
    section = getattr(target, section_name, None)
    return section.get(key) if isinstance(section, dict) else None


def _parse(target, recipe):
    """Every recipe key, absent values as None, so the header shape does not
    depend on which parameters a ParaVision version writes."""
    return {key: _resolve(target, path) for key, path in recipe.items()}


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
        """Subject-level parameters, keyed without their ``SUBJECT_``/``CMN_``
        prefix, plus the JCAMP ``##OWNER`` as ``owner``.

        ``OWNER`` gets its own key: PV360 also writes ``SUBJECT_study_operator``,
        the operator entered at study registration, which is a different person
        from the login that wrote the file (``nmrsu`` vs ``jkl`` in Bruker's own
        PV360 3.7 standard data).
        """
        self.header = None
        if self._subject is None:
            return
        self.header = {key.replace('SUBJECT_', '').replace('CMN_', ''): get_value(self._subject, key)
                       for key in self._subject if key.startswith(('SUBJECT_', 'CMN_'))}
        title = get_value(self._subject, 'TITLE')
        self.header['sw_version'] = (str(title).split(',')[-1].strip()
                                     if title and 'ParaVision' in str(title)
                                     else 'ParaVision < 6')
        self.header['owner'] = get_value(self._subject, 'OWNER')

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
        """Compile study, scan and reconstruction headers from the recipes.

        A scan or reconstruction that cannot be analysed is kept as an entry
        whose header carries only ``error`` -- listing a study must not abort
        because one scan of it is unreadable.
        """
        self._info = StudyHeader(header=_parse(self, _STUDY_RECIPE), scans=[])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for scan_id in self.avail:
                try:
                    scan_header = self._scan_header(scan_id)
                except Exception as error:
                    scan_header = ScanHeader(scan_id=scan_id,
                                             header={'error': str(error)}, recos=[])
                self._info.scans.append(scan_header)

    def _scan_header(self, scan_id):
        """One scan's header and reco headers; reco failures stay per-reco."""
        scanobj = self.get_scan(scan_id)
        scan_header = ScanHeader(scan_id=scan_id,
                                 header=_parse(scanobj.info, _SCAN_RECIPE),
                                 recos=[])
        for reco_id in scanobj.avail:
            try:
                recoinfo = scanobj.get_scaninfo(reco_id=reco_id)
                header = _parse(recoinfo, _RECO_RECIPE)
                header['warns'] = list(recoinfo.warns)
            except Exception as error:
                header = {'error': str(error)}
            scan_header.recos.append(RecoHeader(reco_id=reco_id, header=header))
        return scan_header
