import enum
import os
import pathlib
import re
import warnings

import numpy as np

from ..api.helper.base import image_shape
from . import derived, tabular
from .errors import InvalidApproach, InvalidValueInField, UnexpectedError
from .reference import COMMON_META_REF, ERROR_MESSAGES
from .subject_orient import SUBJECT_POSE, SUBJECT_TYPES, normalize_subject_type
from .utils import encdir_code_converter, get_value, is_all_element_same, meta_get_value

np.set_printoptions(formatter={'float_kind':'{:f}'.format})


@enum.unique
class DataType(enum.Enum):
    PVDATASET = 1
    NIFTI1 = 2


def _bids_fieldmap_units(raw_units):
    """Map a Bruker ``VisuCoreDataUnits`` value to a valid BIDS fieldmap unit.

    BIDS requires fieldmap ``Units`` to be one of ``Hz``, ``rad/s`` or ``T``.
    Returns the matching canonical unit, or ``None`` when no safe mapping exists.
    """
    if isinstance(raw_units, (list, tuple, np.ndarray)):
        raw_units = raw_units[0] if len(raw_units) else None
    if raw_units is None:
        return None
    token = str(raw_units).strip().strip('[]').lower()
    mapping = {'hz': 'Hz', 'rad/s': 'rad/s', 'rad/sec': 'rad/s', 'rads': 'rad/s', 't': 'T'}
    return mapping.get(token)


def _as_json_value(value):
    """Plain Python types for a BIDS sidecar.

    Parameters read back as numpy scalars and arrays, which ``json.dump``
    cannot serialise.
    """
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _as_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_json_value(v) for v in value]
    return value


def _demote_schema_invalid(json_obj, filename):
    """Move values that violate the BIDS schema onto a non-BIDS ``<key>Raw`` key.

    The reference validator feeds every *present* field to a JSON Schema validator,
    so writing a value we can already prove invalid earns a
    ``JSON_SCHEMA_VALIDATION_ERROR`` -- an error, not a warning. Dropping it outright
    would instead lose a real Bruker measurement. Keeping it under a name that is
    honestly not BIDS costs neither: the reading stays in the sidecar, and the
    warning names the field whose mapping needs fixing.

    Values are checked as they will be written, i.e. after every override
    ``save_json`` applies, so what is validated is what lands on disk.
    """
    from . import bids

    checked = {}
    for key, value in json_obj.items():
        problem = bids.value_problem(key, value)
        if problem is None:
            checked[key] = value
            continue
        warnings.warn(f"{filename}.json: '{key}' is not valid BIDS ({problem}); "
                      f"kept as '{key}Raw' so the value is not lost. "
                      f"Its mapping in lib/reference.py needs correcting.")
        checked[f'{key}Raw'] = _as_json_value(value)
    return checked


def load(path):
    """Open a PvDataset -- a study directory, an exported scan, or an archive."""
    from pvraw.app.tonifti import StudyToNifti
    return StudyToNifti(pathlib.Path(path))


_STUDY_DIR_NUMBERS = re.compile(r'_(\d+)_(\d+)$')


def session_and_study_number(name):
    """``(session number, study number)`` from a study directory name, or None.

    ParaVision 6 and later name a study ``<$Date>_<$Time>_<$AnimalID>_<session>_<study>``
    (or Animal ID first, per the "Study Directory Pattern" option) and write the
    session number nowhere else -- not in ``subject``, not in ``visu_pars``
    (``dsetserver.util.NeedFulThings.buildStudyPath``; FILE_FORMAT.md section 1.1,
    ADR 0003). The Animal ID may itself hold underscores, so the two numbers are
    read from the right. PV5 names carry no such suffix.
    """
    found = _STUDY_DIR_NUMBERS.search(name or '')
    return (int(found.group(1)), int(found.group(2))) if found else None


class BrukerLoader:
    """ The front-end handler for Bruker PvDataset

    Reading -- directory and archive traversal, JCAMP-DX parsing and binary
    assembly -- is delegated to `brukerapi` (ADR 0002). What this class adds is
    orientation, NIfTI headers and BIDS metadata.

    Attributes:
        num_scans (int): The number of scan objects on the loaded dataset.
        num_recos (int): The number of reco objects on the loaded dataset.
        is_pvdataset (bool): Return True if imported path is PvDataset, else False

    Methods:
        - get method for data object
        get_dataobj(scan_id, reco_id)
            return the image array, one named axis per Frame Group (numpy.array)
        get_niftiobj(scan_id, reco_id)
            return nibabel's NifTi1Image object

        - get method for parameter objects
        get_acqp(scan_id)
            return acqp parameter object
        get_method(scan_id)
            return method parameter object
        get_visu_pars(scan_id, reco_id)
            return visu_pars parameter object

        - get method for image parameters
        get_affine(scan_id, reco_id)
            return affine transform matrix
        get_bdata(scan_id)
            return bvals, bvecs
        get_scan_time(visu_pars=None)
            return dictionary contains the datetime object for session initiate time
            if visu_pars parameter object is given, it will contains scan start time

        - method to generate files
        save_nifti(scan_id, reco_id, filename, dir='./', ext='nii.gz')
            generate NifTi1 file
        save_bdata(scan_id, filename, dir='./')
            generate FSL's Bdata files for DTI image processing
        save_json(scan_id, reco_id, filename, dir='./')
            generate JSON with given filename for BIDS MRI parameters

        - method to print meta information
        print_bids(scan_id, reco_id, fobj=None)
            print out BIDS MRI parameters defined at reference.py
            if fileobject is given, it will be written in file instead of stdout
        info(fobj=None)
            print out the PvDataset major parameters
            if fileobject is given, it will be written in file instead of stdout

        - method to override header
        override_subjtype(subjtype)
            override subject type (e.g. Biped)
        override_position(position_string)
            state the position the subject was actually in (e.g. Foot_Supine);
            without it Head_Prone is assumed
    """
    def __init__(self, path):
        """ class method to initiate object.
        Args:
            path (str): Path of PvDataset.
        """
        self._path = path
        self._study = load(path)
        self._override_position = None
        self._override_type = None

        # A dataset is loadable as long as scans were found. The study-level
        # `subject` file is optional: individually exported scans (e.g. PV360
        # standalone scans) have no subject but their reconstructions are still
        # readable. Subject-derived fields are None in that case.
        self._is_pvdataset = self.num_scans > 0

    @property
    def pvobj(self):
        """The `brukerapi` folder this dataset reads through."""
        return self._study.pvobj

    @property
    def study(self):
        """The StudyToNifti this loader delegates image assembly to."""
        return self._study

    @property
    def path(self):
        """The dataset's name, as recorded in a BIDS datasheet's ``RawData``."""
        if pathlib.Path(str(self._path)).is_dir():
            return os.path.basename(os.path.normpath(str(self._path)))
        return self._study.pvobj.path.name   # the study directory inside an archive

    def _scan_bridge(self, scan_id, reco_id=None):
        """The ScanToNifti for one scan.

        Every image/affine request funnels through here so a single affine and
        header implementation (AffineAnalyzer + the tonifti Header) serves the
        loader/CLI path, the BIDS conversion, and the app.tonifti API."""
        return self._study.get_scan(scan_id, reco_id)

    @property
    def num_scans(self):
        return len(self._study.avail)

    @property
    def num_recos(self):
        return sum(len(r) for r in self.avail_reco_id.values())

    @property
    def is_pvdataset(self):
        return self._is_pvdataset

    @property
    def avail_scan_id(self):
        """Available ``scan_id``s, ascending."""
        return self._study.avail

    @property
    def avail_reco_id(self):
        """``{scan_id: [reco_id, ...]}`` for every scan holding a reconstruction."""
        return self._study.avail_reco_id

    # subject-level fields; None when the export carries no `subject` file
    @property
    def subject(self):
        """The study's ``subject`` parameter file."""
        return self._study.subject

    def _subject_value(self, key, default=None):
        return get_value(self.subject, key, default)

    @property
    def user_account(self):
        """``##OWNER``: the login that wrote the study (also ``ACQ_operator``)."""
        return self._subject_value('OWNER')

    @property
    def operator(self):
        """The operator entered at study registration: PV360's
        ``SUBJECT_study_operator``, ``SUBJECT_referral`` before it. Not the
        login -- Bruker's own PV360 data has ``nmrsu`` writing for ``jkl``."""
        return (self._subject_value('SUBJECT_study_operator')
                or self._subject_value('SUBJECT_referral'))

    @property
    def subject_name(self):
        """``SUBJECT_name_string``: the subject's name, in DICOM patient-name
        format on PV360 (``family^given^middle^prefix^suffix``)."""
        return self._subject_value('SUBJECT_name_string')

    @property
    def subj_id(self):
        return self._subject_value('SUBJECT_id')

    @property
    def study_id(self):
        return self._subject_value('SUBJECT_study_name')

    @property
    def session_id(self):
        """ParaVision's session number: the visit, which BIDS calls ``ses-``.

        Read from the study directory name, the only place ParaVision writes it
        (ADR 0003). A name without the ``_<session>_<study>`` suffix -- PV5, or
        a renamed directory -- falls back to ``SUBJECT_study_nr``: PV5 has no
        sessions, and there a study is one visit.
        """
        numbers = session_and_study_number(self.path)
        return numbers[0] if numbers else self.study_nr

    @property
    def study_nr(self):
        """``SUBJECT_study_nr``: the study's number inside its session (under a
        project, its study-template slot). Not a session."""
        return self._subject_value('SUBJECT_study_nr')

    @property
    def subj_entry(self):
        """``Head`` or ``Foot``, the vocabulary of ``SUBJECT_POSE`` and
        ``--position``. PV360 records entry and position in one parameter
        (``Head_Prone``); PV5.1/PV6 spell the entry ``SUBJ_ENTRY_HeadFirst``."""
        position = self._subject_value('SUBJECT_study_instrument_position')
        if position is not None:
            return str(position).split('_')[0]
        entry = self._subject_value('SUBJECT_entry')
        if entry is None:
            return None
        entry = str(entry).split('_')[-1]
        return {'HeadFirst': 'Head', 'FeetFirst': 'Foot'}.get(entry, entry)

    @property
    def subj_pose(self):
        position = self._subject_value('SUBJECT_study_instrument_position')
        if position is not None:
            return str(position).split('_')[-1]
        pose = self._subject_value('SUBJECT_position')
        return str(pose).split('_')[-1] if pose is not None else None

    @property
    def subj_sex(self):
        return self._subject_value('SUBJECT_sex') or self._subject_value('SUBJECT_gender')

    @property
    def subj_type(self):
        return self._subject_value('SUBJECT_type')

    @property
    def subj_weight(self):
        return self._subject_value('SUBJECT_weight') or self._subject_value('SUBJECT_study_weight')

    @property
    def subj_dob(self):
        return self._subject_value('SUBJECT_dbirth')

    def override_subjtype(self, subjtype):
        """ override subject type
        Arge:
            subtype(str): subject type that supported by PV
        """
        err_msg = f'Unknown subject type [{subjtype}]'
        subjtype = normalize_subject_type(subjtype)
        if subjtype not in SUBJECT_TYPES:
            raise InvalidValueInField(err_msg)
        self._override_type = subjtype

    def override_position(self, position_string):
        """State the position the subject was actually in.

        The recorded ``VisuSubjectPosition`` is what ParaVision was told, and
        the frame it writes its geometry in; pvraw does not trust it and
        assumes ``Head_Prone`` (prone, head first). Pass the real position
        here when that assumption is wrong (ADR 0001, as amended 2026-08-21).

        Args:
            position_string: ``<BodyPart>_<Side>`` as ParaVision spells it,
                e.g. ``Foot_Supine``.
        """
        err_msg = f'Unknown position string [{position_string}]'
        parts = position_string.split('_')
        if (len(parts) != 2 or parts[0] not in SUBJECT_POSE['part']
                or parts[1] not in SUBJECT_POSE['side']):
            raise InvalidValueInField(err_msg)
        self._override_position = position_string

    def close(self):
        self._study = None

    def get_affine(self, scan_id, reco_id):
        # Delegate to the single affine implementation (AffineAnalyzer via the
        # app.tonifti bridge). The type override rides through as an explicit
        # arg (None reads VisuSubjectType per scan); the position override is
        # the position the animal was actually in (None assumes Head_Prone) --
        # the declared VisuSubjectPosition is always read per scan and rotated
        # away from (ADR 0001, as amended 2026-08-21).
        return self._scan_bridge(scan_id, reco_id).get_affine(
            reco_id=reco_id,
            subj_type=self._override_type,
            subj_position=self._override_position)

    def get_dataobj(self, scan_id, reco_id, scale_mode='apply'):
        """ Return the image array with one named axis per Frame Group
        Args:
            scan_id: scan id
            reco_id: reco id
            scale_mode: 'apply' bakes the intensity slope/offset into the
                values, 'header'/'none' return them as stored.
        Returns:
            dataobj
        """
        return self._scan_bridge(scan_id, reco_id).get_dataobj(
            reco_id=reco_id, scale_mode=scale_mode)

    def get_axis_labels(self, scan_id, reco_id):
        """One name per axis of the image array (``echo``, ``slice``, ...)."""
        return self._scan_bridge(scan_id, reco_id).get_data_dict(reco_id)['axis_labels']

    @property
    def get_visu_pars(self):
        return self._get_visu_pars

    def get_method(self, scan_id):
        """The scan's ``method`` file, or None when the export has none."""
        return self._parameters(scan_id).get('method')

    def get_acqp(self, scan_id):
        """The scan's ``acqp`` file, or None when the export has none."""
        return self._parameters(scan_id).get('acqp')

    def _parameters(self, scan_id, reco_id=None):
        scanobj = self._study.get_scan(scan_id)
        return scanobj.get_dataset(reco_id).parameters

    def get_bdata(self, scan_id):
        return self._get_bdata(self.get_method(scan_id))

    def get_frame_groups(self, scan_id, reco_id):
        """``(name, size)`` for each Frame Group of a reconstruction."""
        from pvraw.api.helper import frame_groups
        return frame_groups(self._study.get_scan(scan_id).get_dataset(reco_id))

    def is_multi_echo(self, scan_id, reco_id):
        """Number of echoes when the reconstruction is genuinely multi-echo, else False.

        A field map stores its two echoes as one derived image and is handled
        separately, so it is not multi-echo here.
        """
        visu_pars = self._get_visu_pars(scan_id, reco_id)
        protocol = str(get_value(visu_pars, 'VisuAcquisitionProtocol') or '')
        if 'FieldMap' in protocol:
            return False
        for name, size in self.get_frame_groups(scan_id, reco_id):
            if name == 'echo':
                # a single echo in an FG_ECHO group is not multi-echo data
                return size if size > 1 else False
        return False

    # methods to dump data into file object
    ## - NifTi1
    def get_niftiobj(self, scan_id, reco_id, crop=None, scale_mode='header'):
        """Return a nibabel Nifti1Image (or a list) for a scan.

        Delegates to the app.tonifti API so this loader/CLI path, the BIDS
        conversion, and the app.tonifti API share one image-assembly
        implementation and cannot diverge. ``scale_mode`` is 'header' (the
        default: intensity slope/offset in scl_slope/scl_inter), 'apply' (baked
        into the data) or 'none' (no rescaling at all). Subject-type/position
        overrides ride through to the affine.
        """
        niiobj = self._scan_bridge(scan_id, reco_id).get_nifti1image(
            reco_id=reco_id, scale_mode=scale_mode,
            subj_type=self._override_type, subj_position=self._override_position)
        if crop is not None:
            from nibabel import Nifti1Image
            sl = slice(crop[0], crop[1])
            objs = niiobj if isinstance(niiobj, list) else [niiobj]
            objs = [Nifti1Image(np.asarray(o.dataobj)[..., sl], o.affine, o.header)
                    for o in objs]
            niiobj = objs if isinstance(niiobj, list) else objs[0]
        return niiobj

    @property
    def save_as(self):
        return self.save_nifti

    def save_nifti(self, scan_id, reco_id, filename, dir='./', ext='nii.gz',
                crop=None, scale_mode='header'):
        niiobj = self.get_niftiobj(scan_id, reco_id, crop=crop, scale_mode=scale_mode)
        if isinstance(niiobj, list):
            for i, nii in enumerate(niiobj):
                output_path = os.path.join(dir,
                                           f'{filename}-{str(i+1).zfill(2)}.{ext}')
                nii.to_filename(output_path)
        else:
            output_path = os.path.join(dir, f'{filename}.{ext}')
            niiobj.to_filename(output_path)

    # - FSL bval, bvec, and bmat
    @staticmethod
    def _reorient_bvecs(bvecs, affine):
        """Express diffusion gradient vectors in the saved NIfTI voxel frame.

        ``bvecs`` is (3, N) as read from PVM_DwGradVec, assumed to be in the
        scanner/world frame. The affine maps voxel -> world
        (world = R.diag(zooms).voxel + t), so a world-frame direction g is
        R^T @ g in voxel axes, where R is the normalized direction-cosine matrix.
        For an axis-aligned acquisition R is a signed permutation and this is a
        no-op up to axis order/sign -- it only rotates OBLIQUE acquisitions, for
        which the previous unrotated vectors were already wrong.

        CAVEAT: that PVM_DwGradVec is world-frame has not been validated against a
        phantom with known gradient directions, and the FSL bvec handedness
        convention is not applied here; verify oblique DWI before trusting the
        b-vectors for tractography.
        """
        rot = np.asarray(affine, dtype=float)[:3, :3]
        norms = np.linalg.norm(rot, axis=0)
        norms[norms == 0] = 1.0
        rot = rot / norms
        return rot.T @ bvecs

    def save_bdata(self, scan_id, filename, dir='./', reco_id=1, num_volumes=None):
        bvals, bvecs = self._get_bdata(self.get_method(scan_id))
        # A multi-cycle/repetition DWI keeps every repeat as a separate volume, so
        # the image holds an integer multiple of the per-direction gradient count
        # with the diffusion block repeated per cycle (FG_CYCLE is the outer frame
        # group). Tile bval/bvec to one entry per volume so they match the NIfTI
        # (a per-direction count vs a multi-volume image is BIDS VOLUME_COUNT_MISMATCH).
        if num_volumes and len(bvals) and num_volumes > len(bvals) \
                and num_volumes % len(bvals) == 0:
            reps = num_volumes // len(bvals)
            bvals = np.tile(bvals, reps)
            bvecs = np.tile(bvecs, reps)
        # Reorient the gradient vectors into the saved image's voxel frame so FSL
        # and BIDS tools read them consistently with the NIfTI. No-op for
        # axis-aligned scans; only rotates oblique ones. See _reorient_bvecs.
        try:
            affine = self.get_affine(scan_id, reco_id)
            if isinstance(affine, list):
                affine = affine[0]
            bvecs = self._reorient_bvecs(bvecs, affine)
        except Exception as exc:
            warnings.warn('Could not reorient b-vectors into the image frame '
                          f'({exc}); writing them unrotated.', UserWarning)
        output_path = os.path.join(dir, filename)

        with open(f'{output_path}.bval', 'w') as bval_fobj:
            bval_fobj.write(' '.join(bvals.astype('str')) + '\n')

        with open(f'{output_path}.bvec', 'w') as bvec_fobj:
            bvec_fobj.writelines(' '.join(row.astype('str')) + '\n' for row in bvecs)

    # BIDS JSON
    def _parse_json(self, scan_id, reco_id, metadata=None):
        parameters = self._parameters(scan_id, reco_id)
        acqp = parameters['acqp']
        method = parameters['method']
        visu_pars = parameters['visu_pars']
        # Listed last so acqp/method/visu_pars keep priority. `reco` is the
        # reconstruction-side parameter file (pdata/N/reco); it is the only place
        # `RecoCombineMode` lives. `configscan` is the scan-level configuration,
        # the only place `CONFIG_SCAN_gradient_system` lives. brukerapi loads
        # both as optional files, so either can be absent for some exports.
        reco = parameters.get('reco')
        configscan = parameters.get('configscan')

        json_obj = {}
        # Resolves the phase-encode AXIS. It is emitted as `PhaseEncodingAxis`, a
        # non-BIDS key, because BIDS `PhaseEncodingDirection` has no unsigned value:
        # a bare 'j' asserts positive polarity. See the note in lib/reference.py.
        encdir_dic = {0: 'i', 1: 'j', 2: 'k'}

        if metadata is None:
            metadata = COMMON_META_REF.copy()
        for k, v in metadata.items():
            val = meta_get_value(v, acqp, method, visu_pars, reco, configscan)
            if k == 'PhaseEncodingAxis' and val is not None:
                # Convert the encoding direction meta data into BIDS format
                # (SliceEncodingDirection is resolved directly to 'k'/None by its
                # mapping and needs no code-to-axis conversion.)
                if isinstance(val, (int, np.integer)):
                    val = encdir_dic[int(val)]
                elif isinstance(val, (list, np.ndarray)):
                    val = list(val)
                    if is_all_element_same(val):
                        # A uniform per-slice direction: reduce to the single
                        # value and convert it like the scalar case below, so a
                        # PV5.1 string code ('col_dir'/'row_dir') becomes a BIDS
                        # axis instead of reaching the sidecar verbatim.
                        v = val[0]
                        if isinstance(v, (int, np.integer)):
                            val = encdir_dic[int(v)]
                        else:
                            encdirs = encdir_code_converter(str(v))
                            val = (encdir_dic[encdirs.index('phase_enc')]
                                   if 'phase_enc' in encdirs else None)
                    else:
                        # handling condition of multiple phase encoding direction
                        updated_val = []
                        for v in val:
                            if isinstance(v, (int, np.integer)):
                                # in PV 6 if each slice package has distinct phase encoding direction
                                updated_val.append(encdir_dic[int(v)])
                            else:
                                # in PV 5.1, element wise code conversion
                                encdirs = encdir_code_converter(str(v))
                                if 'phase_enc' in encdirs:
                                    pe_idx = encdirs.index('phase_enc')
                                    updated_val.append(encdir_dic[pe_idx])
                                else:
                                    updated_val.append(None)
                        val = updated_val
                elif isinstance(val, str):
                    # in PV 5.1, single value code conversion
                    encdirs = encdir_code_converter(val)
                    if 'phase_enc' in encdirs:
                        pe_idx = encdirs.index('phase_enc')
                        val = encdir_dic[pe_idx]
                    else:
                        val = None
                else:
                    raise UnexpectedError('Unexpected phase encoding direction in PV5.1.')
            json_obj[k] = _as_json_value(val)
        return json_obj

    def save_json(self, scan_id, reco_id, filename, dir='./', metadata=None, condition=None,
                  task_name=None, intended_for=None, num_slices=None, repetition_time=None,
                  extra=None):
        json_obj = self._parse_json(scan_id, reco_id, metadata)

        # Fields the caller computed because a per-parameter mapping cannot see what
        # they need -- the method name, the frame-group layout, the written volume
        # count. The ASL block is the whole reason this exists.
        if extra:
            json_obj.update(extra)

        # For func, RepetitionTime is the wall-clock time between volumes, which the
        # converter computes as ScanTime/num_volumes (matching the NIfTI pixdim[4]).
        # This exceeds the sequence VisuAcqRepetitionTime for multi-shot/averaged
        # EPI; anat/dwi keep the sequence TR (they pass repetition_time=None).
        if repetition_time is not None:
            json_obj['RepetitionTime'] = repetition_time

        # SliceTiming must have exactly one entry per reconstructed slice. The
        # mapping derives its length from Bruker NSLICES, which can disagree with
        # the written volume (cropping, slice-pack stacking, single-slice edge
        # cases); when the caller knows the true slice count, drop a mismatched
        # array rather than ship a wrong-length (and thus misleading) SliceTiming.
        if json_obj.get('SliceTiming') is not None and num_slices is not None:
            st = json_obj['SliceTiming']
            st = st if isinstance(st, list) else [st]
            if len(st) == num_slices:
                json_obj['SliceTiming'] = st
            else:
                del json_obj['SliceTiming']
        if condition is not None:
            code, idx = condition
            if code == 'me':    # multi-echo
                if 'EchoTime' in json_obj:
                    te = json_obj['EchoTime']
                    if isinstance(te, list):
                        json_obj['EchoTime'] = te[idx]
                    else:
                        raise InvalidApproach('SingleTE data')
            elif code == 'fm':
                visu_pars = self._get_visu_pars(scan_id, reco_id)
                units = _bids_fieldmap_units(get_value(visu_pars, 'VisuCoreDataUnits'))
                if units is not None:
                    json_obj['Units'] = units
                else:
                    warnings.warn("Could not map Bruker 'VisuCoreDataUnits' to a valid BIDS "
                                  f"fieldmap unit (Hz, rad/s, T); 'Units' omitted from {filename}.json. "
                                  "Set it manually for a valid fieldmap.")
                # IntendedFor (BIDS recommended): subject-relative paths to the target
                # images, set by the converter. Glob patterns are not valid BIDS.
                if intended_for:
                    json_obj['IntendedFor'] = list(intended_for)
            else:
                raise InvalidApproach('Invalid datatype code for json creation')

        # TaskName is REQUIRED for func and must equal the task- entity label.
        if task_name is not None:
            json_obj['TaskName'] = task_name

        # SoftwareVersions is a string in the BIDS schema, but Bruker version
        # fields like <6.0> parse to a float; coerce a present value to str so it
        # validates (a None value is omitted just below).
        if json_obj.get('SoftwareVersions') is not None:
            json_obj['SoftwareVersions'] = str(json_obj['SoftwareVersions'])

        # Omit unmapped fields entirely rather than writing placeholder strings;
        # BIDS sidecars should only contain known values.
        json_obj = {k: v for k, v in json_obj.items() if v is not None}

        # RepetitionTime is mutually exclusive with VolumeTiming, here default with RepetitionTime.
        # https://bids-specification.readthedocs.io/en/latest/04-modality-specific-files/01-magnetic-resonance-imaging-data.html#required-fields
        # To use VolumeTiming, remove the RepetitionTime item in .json file generated from bids_helper.

        if ('RepetitionTime' in json_obj) and ('VolumeTiming' in json_obj) \
                and isinstance(json_obj['RepetitionTime'], (int, float)):
            del json_obj['VolumeTiming']
            msg = "Both 'RepetitionTime' and 'VolumeTiming' exist in your .json file, removed 'VolumeTiming' to make it valid for BIDS.\
            \n To use VolumeTiming, remove the RepetitionTime item but keep VolumeTiming from the .json file generated from bids_helper."
            warnings.warn(msg)

        # Last, so what is validated is exactly what gets written.
        json_obj = _demote_schema_invalid(json_obj, filename)

        with open(os.path.join(dir, f'{filename}.json'), 'w') as f:
            import json
            json.dump(json_obj, f, indent=4)

    def get_scan_time(self, visu_pars=None):
        """Session date and start time, plus the scan end time when given a reco.

        The study date is read in whichever form ParaVision wrote it (see
        ``tabular.parse_datetime``). The end time is ``VisuCreationDate`` on
        PV6 and later; PV5.1 writes that equal to the acquisition start, so
        there it is ``VisuAcqDate`` plus ``VisuAcqScanTime``. PV5.1 is told by
        its date form (``HH:MM:SS D Mon YYYY`` -- no ``T``), as `brukerapi` does.
        """
        import datetime as dt
        raw = self._subject_value('SUBJECT_date') or self._subject_value('SUBJECT_study_date')
        stamp = tabular.parse_datetime(raw)
        if stamp is None:
            raise InvalidValueInField(ERROR_MESSAGES['NotIntegrated'])
        result = {'date': stamp.date(), 'start_time': stamp.time()}
        if visu_pars is not None:
            if isinstance(raw, str) and 'T' not in raw:
                start = tabular.parse_datetime(get_value(visu_pars, 'VisuAcqDate'))
                end = start + dt.timedelta(milliseconds=float(get_value(visu_pars, 'VisuAcqScanTime')))
            else:
                created = get_value(visu_pars, 'VisuCreationDate')
                if isinstance(created, (list, tuple, np.ndarray)):
                    created = created[0] if len(created) else None
                end = tabular.parse_datetime(created)
            result['scan_time'] = end.time()
        return result

    # printing functions / help documents
    def print_bids(self, scan_id, reco_id, fobj=None, metadata=None):
        if fobj is None:
            import sys
            fobj = sys.stdout
        json_obj = self._parse_json(scan_id, reco_id, metadata)
        for k, val in json_obj.items():
            n_tap = int(5 - int(len(k) / 8))
            if len(k) % 8 >= 7:
                n_tap -= 1
            tap = ''.join(['\t'] * n_tap)
            print(f'{k}:{tap}{val}', file=fobj)

    def info_dict(self):
        """The study summary as one JSON-serialisable dict.

        The single source of truth for ``info()`` and ``pvraw info --json``::

            {'study': {...},
             'scans': [{'scan_id': N, ..., 'recos': [{'reco_id': N, ...}]}]}

        Scans stay in acquisition order with their ids as explicit integer
        fields. A scan or reconstruction that could not be read is kept as an
        entry carrying only its id and an ``error`` message -- for a QC
        consumer an unreadable scan is a finding, not something to omit.
        """
        spine = self._study.info
        return _as_json_value({
            'study': self._study_block(dict(spine['header'] or {})),
            'scans': [self._scan_block(scan_id, header)
                      for scan_id, header in spine['scans'].items()]})

    def _study_block(self, header):
        """The recipe's study header, normalised for machine consumers.

        ``sw_version`` becomes ``pv_version`` (brukerapi's normalisation from
        the first readable reconstruction, falling back to the subject-file
        TITLE); ``institution`` and ``station`` come from the same
        reconstruction, the only place ParaVision writes them; the dates turn
        ISO 8601; sex is replaced by its normalised spelling and
        ``weight_kg``/``age_years`` are derived (``lib.tabular``) where the raw
        values allow it. The raw ``weight`` stays -- it keeps ParaVision's unset
        sentinel visible to QC.
        """
        sw_version = header.pop('sw_version', None)
        facts = self._first_reco_facts()
        header['pv_version'] = facts.get('pv_version') or sw_version
        header['institution'] = facts.get('institution')
        header['station'] = facts.get('station')
        # PV360 records the position in one parameter; older versions split it
        # over entry/position, which subj_entry/subj_pose resolve to the same
        # ``Head_Prone`` vocabulary.
        position = self._subject_value('SUBJECT_study_instrument_position')
        if position is None and self.subj_entry and self.subj_pose:
            position = f'{self.subj_entry}_{self.subj_pose}'
        header['position'] = position
        header['session'] = self.session_id
        stamp = tabular.parse_datetime(header.get('date'))
        if stamp:
            header['date'] = stamp.isoformat()
        born = tabular.parse_date(header.get('dob'))
        if born:
            header['dob'] = born.isoformat()
        header['sex'] = tabular.sex(self.subject) or header.get('sex')
        header['weight_kg'] = tabular.weight_kg(self.subject)
        header['age_years'] = tabular.age_years(self.subject)
        return header

    def _first_reco_facts(self):
        """Study-wide facts ParaVision writes per reconstruction, from the first
        readable one: `brukerapi`'s ParaVision version, ``VisuInstitution`` and
        ``VisuStation``. Empty when no reconstruction reads."""
        for scan_id, recos in self.avail_reco_id.items():
            try:
                dataset = self._study.get_scan(scan_id).get_dataset(recos[0])
                visu_pars = self._get_visu_pars(scan_id, recos[0])
                version = self._pv_version(dataset, visu_pars)
            except Exception:
                version = None
            if version is not None:
                return {'pv_version': version,
                        'institution': get_value(visu_pars, 'VisuInstitution'),
                        'station': get_value(visu_pars, 'VisuStation')}
        return {}

    def _scan_block(self, scan_id, header):
        entry = {'scan_id': scan_id,
                 **{k: v for k, v in header.items() if k != 'recos'}}
        if 'error' in header:
            entry['recos'] = []
            return entry
        entry['diffusion'] = self._diffusion_summary(scan_id)
        entry['recos'] = [self._reco_block(scan_id, reco_id, reco_header)
                          for reco_id, reco_header in (header.get('recos') or {}).items()]
        return entry

    def _diffusion_summary(self, scan_id):
        """``{'num_bvals', 'num_directions'}``, or None without diffusion parameters."""
        method = self.get_method(scan_id)
        bvals = get_value(method, 'PVM_DwEffBval')
        bvecs = get_value(method, 'PVM_DwGradVec')
        if bvals is None and bvecs is None:
            return None
        return {'num_bvals': int(np.size(bvals)) if bvals is not None else 0,
                'num_directions': len(bvecs) if bvecs is not None else 0}

    def _reco_block(self, scan_id, reco_id, header):
        if 'error' in header:
            return {'reco_id': reco_id, 'error': header['error']}
        entry = {'reco_id': reco_id, **header}
        # The recipe dicts are cached on the Study; never append into them.
        entry['warns'] = list(header.get('warns') or [])
        try:
            self._enrich_reco(entry, scan_id, reco_id)
        except Exception as error:
            entry['warns'].append(
                f'Could not derive the assembled-image fields ({error}).')
        return entry

    def _enrich_reco(self, entry, scan_id, reco_id):
        """The fields derived from the assembled image rather than the recipe."""
        from . import bids  # deferred: importing bids loads the BIDS schema

        visu_pars = self._get_visu_pars(scan_id, reco_id)
        groups = self.get_frame_groups(scan_id, reco_id)
        _, dim_class = self._get_dim_info(visu_pars)
        entry['dim_class'] = dim_class
        spatial = dim_class == 'spatial_only'
        entry['shape'] = (image_shape(self._study.get_scan(scan_id).get_dataset(reco_id))
                          if spatial else None)
        volumes = [size for name, size in groups
                   if not re.search('slice', name, re.IGNORECASE)]
        entry['num_volumes'] = int(np.prod(volumes or [1]))
        scan_time = entry.get('scan_time_ms')
        entry['temporal_resolution_ms'] = (scan_time / entry['num_volumes']
                                           if scan_time else None)
        entry['frame_groups'] = [[name, int(size)] for name, size in groups]
        entry['derived'] = derived.is_derived(groups)
        entry['bids'] = bids.predict_conversion(self.get_method(scan_id), visu_pars, groups)

    def info(self, io_handler=None):
        """Print the study summary -- the text rendering of ``info_dict``.

        Args:
            io_handler: IO handler where to print out
        """
        if io_handler is None:
            import sys
            io_handler = sys.stdout

        if not self._is_pvdataset:
            io_handler.write(f"'{self.path}' is not a valid PvDataset "
                             "(no subject file or no scans found).\n")
            return

        print('\n'.join(self._render_info(self.info_dict())), file=io_handler)

    @staticmethod
    def _pv_version(dataset, visu_pars):
        """The ParaVision version, as `brukerapi` normalises it.

        ``VisuCreatorVersion`` is not always a bare version -- PV5.1 writes
        ``5.1;5.1``. The direct read stays as the fallback for a dataset whose
        properties did not resolve.
        """
        version = dataset.get('pv_version')
        return str(version) if version is not None else get_value(visu_pars, 'VisuCreatorVersion')

    @classmethod
    def _render_info(cls, info):
        """``info_dict``'s content as the lines ``info`` prints."""
        study = info['study']
        title = f"Paravision {study.get('pv_version')}"
        lines = [title, '-' * len(title)]
        weight_kg = study.get('weight_kg')
        age = study.get('age_years')
        # The UIDs and modalities are in the JSON only: one-line noise to a reader.
        rows = [('User Account', study.get('user_account')),
                ('Operator', study.get('operator')),
                ('Institution', study.get('institution')),
                ('Station', study.get('station')),
                ('Date', study.get('date')),
                ('Subject ID', study.get('subject_id')),
                ('Subject Name', study.get('subject_name')),
                ('Session ID', study.get('session')),
                ('Study Name', study.get('study_name')),
                ('Study Nr', study.get('study_nr')),
                ('Purpose', study.get('purpose')),
                ('Study Comment', study.get('study_comment')),
                ('Remarks', study.get('remarks')),
                ('Date of Birth', study.get('dob')),
                ('Sex', study.get('sex')),
                ('Age', f'{age} years' if age is not None else None),
                ('Weight', f'{weight_kg} kg' if weight_kg is not None
                           else study.get('weight')),
                ('Subject Type', study.get('subject_type')),
                ('Position', study.get('position')),
                ('ATS', study.get('use_ats')),
                ('Animal Bed', study.get('animal_bed'))]
        lines.extend(f'{label + ":":<15}{value}' for label, value in rows
                     if value is not None)
        lines.append('\n[ScanID]  Sequence::Protocol::ScanName')
        for scan in info['scans']:
            lines.extend(cls._render_scan(scan))
        lines.append('')
        return lines

    @classmethod
    def _render_scan(cls, scan):
        sid = str(scan['scan_id']).zfill(3)
        if 'error' in scan:
            return [f'[{sid}]  ERROR: {scan["error"]}']
        lines = [(f'[{sid}]  {scan.get("sequence")}::{scan.get("protocol")}'
                  f'::{scan.get("scan_name")}'),
                 '      [ TR: {} ms, TE: {} ms, pixelBW: {} Hz, FlipAngle: {} degree ]'
                 .format(cls._fmt_num(scan.get('tr_ms')), cls._fmt_num(scan.get('te_ms')),
                         cls._fmt_num(scan.get('pixel_bandwidth_hz')),
                         cls._fmt_num(scan.get('flip_angle_deg')))]
        extras = [(label, scan.get(key)) for label, key in
                  (('acquired', 'acq_date'), ('nucleus', 'nucleus'),
                   ('NA', 'num_averages'), ('NR', 'num_repetitions'),
                   ('TI', 'ti_ms'), ('ETL', 'echo_train_length'))]
        extras = [f'{label}: {cls._fmt_num(value)}{" ms" if label == "TI" else ""}'
                  for label, value in extras if value is not None]
        if extras:
            lines.append('      [ ' + ', '.join(extras) + ' ]')
        for reco in scan.get('recos') or []:
            lines.extend(cls._render_reco(reco))
        return lines

    @classmethod
    def _render_reco(cls, reco):
        rid = str(reco['reco_id']).zfill(2)
        if 'error' in reco:
            return [f'    [{rid}] ERROR: {reco["error"]}']
        if reco.get('dim_class') != 'spatial_only':
            return [f'    [{rid}] dim: {reco.get("dim")}, {reco.get("dim_class")}']
        shape = ' x '.join(map(str, reco.get('shape') or []))
        fov = ' x '.join(map(str, reco.get('fov_mm') or []))
        resol = list(reco.get('resolution_mm') or [])
        if len(resol) == 2 and reco.get('slice_distances_mm'):
            resol = resol + [reco['slice_distances_mm'][0]]
        s_resol = ' x '.join(f'{r:.3f}' for r in resol)
        t_resol = reco.get('temporal_resolution_ms')
        t_resol = f'{t_resol:.3f}' if t_resol is not None else ''
        lines = [(f'    [{rid}] dim: {reco.get("dim")}D, matrix_size: {shape}, '
                  f'fov_size: {fov} (unit:mm)'),
                 (f'         spatial_resol: {s_resol} (unit:mm), '
                  f'temporal_resol: {t_resol} (unit:ms)')]
        tags = []
        if reco.get('derived'):
            tags.append('derived')
        if reco.get('bids'):
            tags.append('bids: ' + '/'.join(
                filter(None, [reco['bids'].get('datatype'), reco['bids'].get('suffix')])))
        if tags:
            lines.append('         ' + ', '.join(tags))
        lines.extend(f'         warning: {warn}' for warn in reco.get('warns') or [])
        return lines

    @staticmethod
    def _fmt_num(value):
        """Numbers as ``info`` prints them: 2 decimals, lists comma-joined."""
        if value is None:
            return ''
        if isinstance(value, (list, tuple)):
            return ','.join(BrukerLoader._fmt_num(v) for v in value)
        if isinstance(value, float):
            return f'{value:.2f}'
        return str(value)

    # DTI
    @staticmethod
    def _get_bdata(method):
        """Extract, format, and return diffusion bval and bvec"""
        bvals = np.array(get_value(method, 'PVM_DwEffBval'))
        bvecs = np.array(np.asarray(get_value(method, 'PVM_DwGradVec')).T)
        # Correct for single b-vals
        if np.size(bvals) < 2:
            bvals = np.array([bvals])
        # Normalize bvecs
        bvecs_axis = 0
        bvecs_L2_norm = np.atleast_1d(np.linalg.norm(bvecs, 2, bvecs_axis))
        bvecs_L2_norm[bvecs_L2_norm < 1e-15] = 1
        bvecs = bvecs / np.expand_dims(bvecs_L2_norm, bvecs_axis)
        return bvals, bvecs

    @staticmethod
    def _get_dim_info(visu_pars):
        """check if the frame contains only spatial components"""
        dim = int(get_value(visu_pars, 'VisuCoreDim'))
        dim_desc = [str(d) for d in np.atleast_1d(get_value(visu_pars, 'VisuCoreDimDesc'))]

        if not all(x == 'spatial' for x in dim_desc):
            if 'spectroscopic' in dim_desc:
                return dim, 'contain_spectroscopic'  # spectroscopic data
            elif 'temporal' in dim_desc:
                return dim, 'contain_temporal'  # unexpected data
            else:
                return dim, 'contain_other'  # other non-image content
        else:
            return dim, 'spatial_only'

    def _get_slice_info(self, scan_id, reco_id):
        """Slice packages of a reconstruction: counts and distances per pack."""
        return self._study.get_scan(scan_id).get_scaninfo(reco_id).slicepack

    def _get_visu_pars(self, scan_id, reco_id):
        self._inspect_ids(scan_id, reco_id)
        return self._study.get_scan(scan_id).get_visu_pars(reco_id)

    def _inspect_ids(self, scan_id, reco_id):
        avail = self.avail_reco_id
        if scan_id not in avail:
            print('[Error] Invalid Scan ID.\n'
                  f'  - Your input: {scan_id}\n'
                  f'  - Available Scan IDs: {list(avail.keys())}')
            raise ValueError
        if reco_id not in avail[scan_id]:
            print('[Error] Invalid Reco ID.\n'
                  f'  - Your input: {reco_id}\n'
                  f'  - Available Reco IDs: {avail[scan_id]}')
            raise ValueError
