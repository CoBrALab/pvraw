import enum
import os
import pathlib
import re
import warnings

import numpy as np

from ..api.helper.base import image_shape
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
            override position of subject (e.g. Head_Prone)
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
        return self._subject_value('OWNER')

    @property
    def user_name(self):
        return self._subject_value('SUBJECT_name_string')

    @property
    def subj_id(self):
        return self._subject_value('SUBJECT_id')

    @property
    def study_id(self):
        return self._subject_value('SUBJECT_study_name')

    @property
    def session_id(self):
        return self._subject_value('SUBJECT_study_nr')

    @property
    def subj_entry(self):
        # PV360 records entry and position in one parameter
        position = self._subject_value('SUBJECT_study_instrument_position')
        if position is not None:
            return str(position).split('_')[0]
        entry = self._subject_value('SUBJECT_entry')
        return str(entry).split('_')[-1] if entry is not None else None

    @property
    def subj_pose(self):
        position = self._subject_value('SUBJECT_study_instrument_position')
        if position is not None:
            return str(position).split('_')[-1]
        pose = self._subject_value('SUBJECT_position')
        return str(pose).split('_')[-1] if pose is not None else None

    @property
    def subj_sex(self):
        return self._subject_value('SUBJECT_sex')

    @property
    def subj_type(self):
        return self._subject_value('SUBJECT_type')

    @property
    def subj_weight(self):
        return self._subject_value('SUBJECT_weight')

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
        """ override subject position
        Arge:
            position_string: subject position that supported by PV
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
        # app.tonifti bridge). Subject-type/position overrides ride through as
        # explicit args; None lets the analyzer read them per-scan from
        # VisuSubjectType/VisuSubjectPosition (FILE_FORMAT.md 7.5/7.7).
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

        ParaVision writes the subject date in one of two forms: a PV5.1
        ``HH:MM:SS D Mon YYYY`` or an ISO ``YYYY-MM-DDTHH:MM:SS`` optionally
        followed by a fraction and UTC offset.
        """
        import datetime as dt
        subject_date = self._subject_value('SUBJECT_date')
        if isinstance(subject_date, (list, tuple, np.ndarray)):
            subject_date = subject_date[0] if len(subject_date) else None
        subject_date = str(subject_date)

        legacy = re.match(r'(\d{2}:\d{2}:\d{2})\s+(\d+\s\w+\s\d{4})', subject_date)
        iso = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})', subject_date)

        if legacy:
            start_time = dt.time(*map(int, legacy.group(1).split(':')))
            # Naive on purpose: Bruker records scanner wall-clock with no zone,
            # and only the calendar date is kept. Attaching one would shift it.
            date = dt.datetime.strptime(legacy.group(2), '%d %b %Y').date()  # noqa: DTZ007
            if visu_pars is not None:
                acq_date = str(get_value(visu_pars, 'VisuAcqDate'))
                last = re.match(r'(\d{2}:\d{2}:\d{2})', acq_date)
                acq_time = get_value(visu_pars, 'VisuAcqScanTime') / 1000.0
                scan_time = (dt.datetime.combine(date, dt.time(*map(int, last.group(1).split(':'))))
                             + dt.timedelta(0, acq_time)).time()
                return {'date': date, 'start_time': start_time, 'scan_time': scan_time}
        elif iso:
            start_time = dt.time(*map(int, iso.group(2).split(':')))
            date = dt.date(*map(int, iso.group(1).split('-')))
            if visu_pars is not None:
                created = str(np.atleast_1d(get_value(visu_pars, 'VisuCreationDate'))[0])
                stamp = re.match(r'\d{4}-\d{2}-\d{2}T(\d{2}:\d{2}:\d{2})', created)
                return {'date': date, 'start_time': start_time,
                        'scan_time': dt.time(*map(int, stamp.group(1).split(':')))}
        else:
            raise InvalidValueInField(ERROR_MESSAGES['NotIntegrated'])

        return {'date': date, 'start_time': start_time}

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

    def info(self, io_handler=None):
        """ Prints out the information of the internal contents in Bruker raw data
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

        lines = []
        for i, (scan_id, recos) in enumerate(self.avail_reco_id.items()):
            for j, reco_id in enumerate(recos):
                visu_pars = self._get_visu_pars(scan_id, reco_id)
                if i == 0 and j == 0:
                    lines.extend(self._info_header(
                        self._study.get_scan(scan_id).get_dataset(reco_id), visu_pars))
                tr = get_value(visu_pars, 'VisuAcqRepetitionTime')
                tr = ','.join(map(str, tr)) if isinstance(tr, (list, np.ndarray)) else tr
                te = get_value(visu_pars, 'VisuAcqEchoTime')
                te = 0 if te is None else te
                te = ','.join(map(str, te)) if isinstance(te, (list, np.ndarray)) else te
                pixel_bw = get_value(visu_pars, 'VisuAcqPixelBandwidth')
                flip_angle = get_value(visu_pars, 'VisuAcqFlipAngle')
                scanname = get_value(self.get_acqp(scan_id), 'ACQ_scan_name')
                param_values = [tr, te, pixel_bw, flip_angle]
                for k, v in enumerate(param_values):
                    if v is None:
                        param_values[k] = ''
                    if isinstance(v, float):
                        param_values[k] = f'{v:.2f}'
                if j == 0:
                    params = "[ TR: {} ms, TE: {} ms, pixelBW: {} Hz, FlipAngle: {} degree]".format(
                        *param_values)
                    protocol_name = get_value(visu_pars, 'VisuAcquisitionProtocol')
                    sequence_name = get_value(visu_pars, 'VisuAcqSequenceName')
                    lines.append(f'[{str(scan_id).zfill(3)}]\t{sequence_name}::{protocol_name}::{scanname}\n\t{params}')
                lines.append(self._info_reco(scan_id, reco_id, visu_pars))
        lines.append('\n')
        print('\n'.join(lines), file=io_handler)

    @staticmethod
    def _pv_version(dataset, visu_pars):
        """The ParaVision version, as `brukerapi` normalises it.

        ``VisuCreatorVersion`` is not always a bare version -- PV5.1 writes
        ``5.1;5.1``. The direct read stays as the fallback for a dataset whose
        properties did not resolve.
        """
        version = dataset.get('pv_version')
        return str(version) if version is not None else get_value(visu_pars, 'VisuCreatorVersion')

    def _info_header(self, dataset, visu_pars):
        """The study-level block of ``info``."""
        title = f'Paravision {self._pv_version(dataset, visu_pars)}'
        lines = [title, '-' * len(title)]
        try:
            datetime = self.get_scan_time()
        except Exception:
            datetime = {'date': 'None'}
        lines.append(f'UserAccount:\t{self.user_account}')
        lines.append('Date:\t\t{}'.format(datetime['date']))
        lines.append(f'Researcher:\t{self.user_name}')
        lines.append(f'Subject ID:\t{self.subj_id}')
        lines.append(f'Session ID:\t{self.session_id}')
        lines.append(f'Study ID:\t{self.study_id}')
        lines.append(f'Date of Birth:\t{self.subj_dob}')
        lines.append(f'Sex:\t\t{self.subj_sex}')
        lines.append(f'Weight:\t\t{self.subj_weight} kg')
        lines.append(f'Subject Type:\t{self.subj_type}')
        lines.append(f'Position:\t{self.subj_pose}\t\tEntry:\t{self.subj_entry}')
        lines.append('\n[ScanID]\tSequence::Protocol::[Parameters]')
        return lines

    def _info_reco(self, scan_id, reco_id, visu_pars):
        """The per-reconstruction line of ``info``."""
        dim, cls = self._get_dim_info(visu_pars)
        if cls != 'spatial_only':
            return f'    [{str(reco_id).zfill(2)}] dim: {dim}, {cls}'
        scanobj = self._study.get_scan(scan_id)
        info = scanobj.get_scaninfo(reco_id)
        size = ' x '.join(map(str, image_shape(scanobj.get_dataset(reco_id))))
        fov_size = ' x '.join(map(str, info.image['field_of_view']))
        resol = list(info.image['resolution'])
        if len(resol) == 2:
            resol = resol + [info.slicepack['slice_distances_each_pack'][0]]
        s_resol = ' x '.join([f'{r:.3f}' for r in resol])
        volumes = [size for name, size in self.get_frame_groups(scan_id, reco_id)
                   if not re.search('slice', name, re.IGNORECASE)]
        num_volumes = int(np.prod(volumes or [1]))
        t_resol = '{:.3f}'.format(info.cycle['scan_time'] / num_volumes)
        return ('    [{}] dim: {}D, matrix_size: {}, fov_size: {} (unit:mm)\n'
                '         spatial_resol: {} (unit:{}), temporal_resol: {} (unit:{})'.format(
                    str(reco_id).zfill(2), dim, size, fov_size,
                    s_resol, info.image['unit'], t_resol, info.cycle['unit']))

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
