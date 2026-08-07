import os
import re
from functools import partial, reduce

import numpy as np

from .errors import InvalidApproach, InvalidValueInField
from .reference import ERROR_MESSAGES


def get_value(parameters, key, default=None):
    """The value of `key`, with the JCAMP-DX representation resolved.

    Two things happen here. A string parameter comes back as the format writes
    it -- ``<Bruker:FLASH>`` -- and is unquoted; a struct array -- ``(a, b)
    (c, d)`` -- is returned as a list of rows even when it has only one row,
    which the plain value accessor flattens.

    `default` matters as much as either: which parameters a file carries is
    ParaVision-version dependent, so a read a PV6 dataset satisfies can be
    absent on PV5.1. Absence returns `default` rather than raising.
    """
    if parameters is None or key not in parameters:
        return default
    parameter = parameters.get_parameter(key)
    is_struct = str(getattr(parameter, 'val_str', '')).lstrip().startswith('(')
    return unquote(parameter.nested if is_struct else parameter.value)


def unquote(value):
    """Resolve a JCAMP-DX scalar to absence or itself.

    `brukerapi` types the value: a bare numeric literal arrives as an int or a
    float, a ``<...>`` string arrives as a str without its delimiters (ADR
    0002; isi-nmr/brukerapi-python#176). All that is left to decide is absence
    -- an empty literal (``<>``, or a parameter written with no value) is
    absence rather than the empty string.

    Notably *not* re-typed. A numeric-looking string is a string: ParaVision
    writes identifiers such as ``<01>``, and coercing those to numbers dropped
    the leading zeros that BIDS turns into ``sub-``/``ses-`` names.
    """
    if isinstance(value, str):
        return value or None
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in ('U', 'S', 'O'):
            return value
        unquoted = [unquote(v) for v in value.ravel().tolist()]
        return np.array(unquoted, dtype=object).reshape(value.shape)
    if isinstance(value, (list, tuple)):
        return type(value)(unquote(v) for v in value)
    return value


def is_all_element_same(listobj):
    if listobj is None:
        return True
    else:
        return all(map(partial(lambda x, y: x == y, y=listobj[0]), listobj))


def is_numeric(x):
    return any([isinstance(x, float), isinstance(x, int)])


def multiply_all(list):
    return reduce(lambda x, y: x*y, list)


# META handler
def meta_get_value(value, *sources):
    """Resolve one ``*_META_REF`` entry against the scan's parameter files.

    ``sources`` are parameter objects in priority order -- ``acqp``, ``method``,
    ``visu_pars``, and optionally ``reco``. Taking them variadically rather than as
    fixed arguments is what lets a mapping reach a parameter that lives outside the
    original three (``RecoCombineMode`` is in ``pdata/N/reco``) without touching
    every resolver in this module.
    """
    if isinstance(value, str):
        return meta_check_source(value, *sources)
    elif isinstance(value, dict):
        if is_keywhere(value):
            return meta_check_where(value, *sources)
        elif is_keyindex(value):
            return meta_check_index(value, *sources)
        elif is_express(value):
            return meta_check_express(value, *sources)
        else:
            parser = {}
            for k, v in value.items():
                sub = meta_get_value(v, *sources)
                if sub is not None:
                    parser[k] = sub
            # Drop the whole group when nothing resolved, so empty objects are omitted.
            return parser if parser else None
    elif isinstance(value, list):
        # Fallback list: try each candidate in order, return the first resolved value.
        for vi in value:
            val = meta_get_value(vi, *sources)
            if val is not None:
                return val
        return None
    else:
        return value


def is_keywhere(value):
    return all(k in value for k in ['key', 'where'])


def is_keyindex(value):
    return all(k in value for k in ['key', 'idx'])


def is_express(value):
    return 'Equation' in value


def meta_check_where(value, *sources):
    """The position of a marker within a parameter's values (e.g. the phase axis)."""
    val = meta_get_value(value['key'], *sources)
    if val is None:
        return None
    # a multi-valued parameter reads back as an array; index it as a sequence
    values = list(np.atleast_1d(val))
    where = value['where'] if isinstance(value['where'], str) \
        else meta_get_value(value['where'], *sources)
    return values.index(where) if where in values else None


def meta_check_index(value, *sources):
    val = meta_get_value(value['key'], *sources)
    if val is not None:
        if isinstance(value['idx'], int):
            return val[value['idx']]
        else:
            idx = meta_get_value(value['idx'], *sources)
        if idx is not None:
            return val[idx]
        else:
            return None
    else:
        return None


def meta_check_express(value, *sources):
    # Resolve every non-Equation key to a variable, then eval the Equation
    # against them. The previous implementation assigned the variables with
    # exec() into locals() and read the result back from locals(); PEP 667
    # (Python 3.13+) made locals() a snapshot, so that pathway silently produced
    # None for every equation-based field (EchoTime, MagneticFieldStrength,
    # SliceTiming, EffectiveEchoSpacing, TotalReadoutTime, DwellTime, ...).
    namespace = {}
    for k, v in value.items():
        if k == 'Equation':
            continue
        val = meta_get_value(v, *sources)
        if isinstance(val, str):
            val = None
        namespace[k] = val
    equation = value['Equation']
    if any(v is None and re.search(rf'\b{re.escape(k)}\b', equation)
           for k, v in namespace.items()):
        # A parameter *used by the equation* is missing; omit the field rather
        # than evaluating with None (which would emit 'None'/nan into the
        # sidecar). Unused declared variables do not suppress the field.
        return None
    try:
        return eval(equation, {'np': np}, namespace)
    except Exception:
        return None


def meta_check_source(key_string, *sources):
    """The first of `sources` carrying `key_string`, else None.

    A parameter absent from every source omits the field rather than echoing
    the Bruker parameter name as the metadata value.
    """
    for parameters in sources:
        if parameters is not None and key_string in parameters:
            return get_value(parameters, key_string)
    return None


def yes_or_no(question):
    while True:
        reply = str(input(question + ' (y/n): ')).lower().strip()
        if reply[:1] == 'y':
            return True
        elif reply[:1] == 'n':
            return False
        else:
            print('  The answer is invalid!')


def convert_unit(size_in_bytes, unit):
    """ Convert the size from bytes to other units like KB, MB or GB"""
    size = float(size_in_bytes)
    if unit == 1:
        return size / 1024
    elif unit == 2:
        return size / (1024 * 1024)
    elif unit == 3:
        return size / (1024 * 1024 * 1024)
    elif unit == 4:
        return size / (1024**unit)
    else:
        return int(size)


def get_dirsize(dir_path):
    unit_dict = {0: 'B',
                 1: 'KB',
                 2: 'MB',
                 3: 'GB',
                 4: 'TB'}
    dir_size = 0
    for root, dirs, files in os.walk(dir_path):
        for f in files:
            fp = os.path.join(root, f)
            if not os.path.islink(fp):
                dir_size += os.path.getsize(fp)

    unit = int(len(str(dir_size)) / 3)
    return convert_unit(dir_size, unit), unit_dict[unit]


def get_filesize(file_path):
    unit_dict = {0: 'B',
                 1: 'KB',
                 2: 'MB',
                 3: 'GB'}
    file_size = os.path.getsize(file_path)

    unit = int(len(str(file_size)) / 3)
    return convert_unit(file_size, unit), unit_dict[unit]


def bids_validation(df, idx, key, val, num_char_allowed, dtype=None):
    import string
    col = string.ascii_uppercase[df.columns.tolist().index(key)]
    special_char = re.compile(r'[^0-9a-zA-Z]')
    str_val = str(val)
    loc = f'col,row:[{col},{idx + 2}]'
    if len(str_val) > num_char_allowed:
        message = f"{loc} You can't use more than {num_char_allowed} characters."
        raise InvalidValueInField(message)
    matched = special_char.search(str_val)
    if matched is not None:
        if ' ' in matched.group():
            message = f"{loc} Empty string is not allowed."
        else:
            message = f"{loc} Special characters are not allowed."
        raise InvalidValueInField(message)
    if dtype is not None:
        try:
            dtype(val)
        except Exception:
            message = f"{loc} Invalid data type. Value must be {dtype.__name__}."
            raise InvalidValueInField(message)
    return True


def get_bids_ref_obj(ref_path, row):
    import json
    if os.path.exists(ref_path) and ref_path.lower().endswith('.json'):
        with open(ref_path) as f:
            ref_data = json.load(f)
        ref = ref_data['common']
        if row.modality in ['bold', 'cbv', 'epi'] and 'func' in ref_data:
            # AcquisitionDuration is deprecated by BIDS for func (superseded by
            # FrameAcquisitionDuration, which Bruker never writes) while staying
            # optional elsewhere -- so it is dropped here and kept for anat/dwi.
            ref.pop('AcquisitionDuration', None)
            for k, v in ref_data['func'].items():
                if k in ref:
                    raise InvalidApproach(f'Duplicated key is found at func: {k}')
                else:
                    ref[k] = v
        # the below may not optimal for Bruker system,
        # only fieldmap and magnitude
        if row.modality in ['fieldmap', 'phase1', 'phase2',
                            'phasediff', 'magnitude',
                            'magnitude1', 'magnitude2'] and 'fmap' in ref_data:
            for k, v in ref_data['fmap'].items():
                if k in ref:
                    raise InvalidApproach(f'Duplicated key is found at func: {k}')
                else:
                    ref[k] = v
    else:
        ref = None
    return ref


def func_volume_tr(dset, row, num_volumes):
    """BIDS func RepetitionTime (seconds): the wall-clock time between volumes.

    For func this is ScanTime/num_volumes, which matches the NIfTI pixdim[4] and,
    unlike the sequence VisuAcqRepetitionTime, is correct for multi-shot/segmented
    or averaged EPI (where one volume spans several TRs). Returns None for non-func,
    non-4D, or when ScanTime is unavailable -- those keep the sequence TR.
    """
    if not re.search('func', str(row.DataType), re.IGNORECASE):
        return None
    if not num_volumes or num_volumes < 2:
        return None
    scan_time = get_value(dset.get_visu_pars(row.ScanID, row.RecoID), 'VisuAcqScanTime')
    if not isinstance(scan_time, (int, float)) or scan_time <= 0:
        return None
    return (scan_time / num_volumes) / 1000.0


def build_bids_json(dset, row, fname, json_path, scale_mode='header', intended_for=None):
    import pandas as pd

    # TaskName is required for func and must equal the task- entity label.
    task_name = row.task if (pd.notnull(row.task) and re.search('func', str(row.DataType),
                                                                re.IGNORECASE)) else None

    if pd.notnull(row.Start) or pd.notnull(row.End):
        crop = [int(row.Start), int(row.End)]
    else:
        crop = None
    if dset.is_multi_echo(row.ScanID, row.RecoID):  # multi_echo
        nii_objs = dset.get_niftiobj(row.ScanID, row.RecoID, crop=crop, scale_mode=scale_mode)
        for echo, nii in enumerate(nii_objs):
            # caught a bug here for multiple echo, changed fname to currentFileName
            currentFileName = f'{fname}_echo-{echo + 1}_{row.modality}'
            output_path = os.path.join(row.Dir, currentFileName)
            nii.to_filename(f'{output_path}.nii.gz')
            if json_path:
                ref = get_bids_ref_obj(json_path, row)
                nslices = nii.shape[2] if nii.ndim >= 3 else 1
                nvol = nii.shape[3] if nii.ndim >= 4 else 1
                dset.save_json(row.ScanID, row.RecoID, currentFileName, dir=row.Dir,
                               metadata=ref, condition=['me', echo], task_name=task_name,
                               num_slices=nslices,
                               repetition_time=func_volume_tr(dset, row, nvol))
    else:
        niiobj = dset.get_niftiobj(row.ScanID, row.RecoID, crop=crop, scale_mode=scale_mode)
        # A multi-slicepack acquisition reconstructs to several images. Give each a
        # BIDS ``chunk-`` entity (with its own sidecar / bval-bvec) rather than
        # appending an invalid ``-NN`` suffix to the stem and leaving one shared
        # sidecar with no matching data file.
        chunks = niiobj if isinstance(niiobj, list) else [niiobj]
        for i, nii in enumerate(chunks):
            if len(chunks) > 1:
                current = f'{fname}_chunk-{str(i + 1).zfill(2)}_{row.modality}'
            else:
                current = f'{fname}_{row.modality}'
            nii.to_filename(os.path.join(row.Dir, f'{current}.nii.gz'))
            if re.search('dwi', row.modality, re.IGNORECASE):
                # DTI parameter (FSL style); one bval/bvec per written volume
                nvol = nii.shape[3] if nii.ndim >= 4 else 1
                dset.save_bdata(row.ScanID, current, dir=row.Dir, reco_id=row.RecoID,
                                num_volumes=nvol)
            # magnitude data does not require JSON (BIDS)
            if json_path and not re.search('magnitude', row.modality, re.IGNORECASE):
                ref = get_bids_ref_obj(json_path, row)
                condition = ['fm', None] if re.search('fieldmap', row.modality, re.IGNORECASE) else None
                # Slice/volume counts from the written image (authoritative for the
                # SliceTiming length check inside save_json).
                num_slices = nii.shape[2] if nii.ndim >= 3 else 1
                nvol = nii.shape[3] if nii.ndim >= 4 else 1
                dset.save_json(row.ScanID, row.RecoID, current, dir=row.Dir,
                               metadata=ref, condition=condition,
                               task_name=task_name, intended_for=intended_for,
                               num_slices=num_slices,
                               repetition_time=func_volume_tr(dset, row, nvol))


def encdir_code_converter(enc_param):
    # for PV 5.1, #TODO: incompleted code.
    if enc_param == 'col_dir':
        return ['read_enc', 'phase_enc']
    elif enc_param == 'row_dir':
        return ['phase_enc', 'read_enc']
    elif enc_param == 'col_slice_dir':
        return ['read_enc', 'phase_enc', 'slice_enc']
    elif enc_param == 'row_slice_dir':
        return ['phase_enc', 'read_enc', 'slice_enc']
    else:
        raise InvalidValueInField(ERROR_MESSAGES['PhaseEncDir'])


def mkdir(path):
    os.makedirs(path, exist_ok=True)


# brkraw-legacy script
def set_rescale(args):
    """The scale mode the --ignore-* options select.

    Intensity rescaling is one switch now: `brukerapi` exposes a single scaling
    boolean, so slope cannot be suppressed without offset (ADR 0002).
    --ignore-slope and --ignore-offset are kept as aliases of --ignore-rescale.
    """
    if args.ignore_rescale or args.ignore_slope or args.ignore_offset:
        return 'none'
    return 'header'


def save_meta_files(study, args, scan_id, reco_id, output_fname):
    method = str(get_value(study.get_method(scan_id), 'Method'))
    if re.search('dti', method, re.IGNORECASE):
        study.save_bdata(scan_id, output_fname, reco_id=reco_id)
    if args.bids:
        study.save_json(scan_id, reco_id, output_fname)
