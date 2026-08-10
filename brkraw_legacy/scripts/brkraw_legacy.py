import argparse
import os
import re
import warnings

from .. import BrukerLoader, __version__
from ..lib import asl, derived
from ..lib.errors import FileNotValidError, InvalidApproach, ValueConflictInField
from ..lib.utils import get_value, mkdir, save_meta_files, set_rescale


def main():
    parser = argparse.ArgumentParser(prog='brkraw-legacy',
                                     description="BrkRaw-legacy command-line interface")
    parser.add_argument("-v", "--version", action='version', version=f'%(prog)s v{__version__}')

    subparsers = parser.add_subparsers(title='Sub-commands',
                                       description='To run this command, you must specify one of the functions listed'
                                                   'below next to the command. For more information on each function, '
                                                   'use -h next to the function name to call help document.',
                                       help='description',
                                       dest='function',
                                       metavar='command')

    # Help text shared by more than one sub-command, so the same option cannot end up
    # documented two different ways. Every option states its default here.
    input_str = "input raw Bruker data"
    input_dir_str = "input directory that contains multiple raw Bruker data"
    output_dir_str = "output directory name (default: Data)"
    output_fnm_str = ("output filename, without the extension (default: <SubjID>_<StudyID>, "
                      "or the name of the input folder when the dataset has no subject file)")
    bids_opt = ("create a JSON file contains metadata based on BIDS recommendation "
                "(default: no JSON file)")
    subjtype_opt = ("override subject type in case the original setting was not properly set. "
                    "available options are (Biped, Quadruped, Phantom, Other, OtherAnimal) "
                    "(default: the subject type recorded in the data)")
    position_opt = ("override position information in case the original setting was not properly "
                    "input. the position variable can be defiend as <BodyPart>_<Side>, available "
                    "BodyParts are (Head, Foot, Tail) and sides are (Supine, Prone, Left, Right). "
                    "(e.g. Head_Supine) (default: the position recorded in the data)")
    # ADR 0002: brukerapi exposes one scaling switch, so slope and offset cannot be
    # suppressed independently. --ignore-slope and --ignore-offset are aliases.
    rescale_opt = ("write the raw stored values, with no slope or offset in the header "
                   "(default: keep the scaling)")
    slope_opt = f"alias of --ignore-rescale, slope cannot be suppressed on its own; {rescale_opt}"
    offset_opt = f"alias of --ignore-rescale, offset cannot be suppressed on its own; {rescale_opt}"
    localizer_opt = ("skip the scan if it is a localizer/tripilot "
                     "(default: skip; pass --no-ignore-localizer to convert them)")

    info = subparsers.add_parser("info", help='Prints out the information of the internal contents in Bruker raw data')
    info.add_argument("input", help=input_str, type=str)

    nii = subparsers.add_parser("tonii", help='Convert a single raw Bruker data into NifTi file(s)')
    niiall = subparsers.add_parser("tonii_all", help="Convert All raw Bruker data located in the input directory")
    bids_helper = subparsers.add_parser("bids_helper", help="Creates a BIDS datasheet "
                                                            "for guiding BIDS data converting.")
    bids_convert = subparsers.add_parser("bids_convert", help="Convert ALL raw Bruker data located "
                                                              "in the input directory based on the BIDS datasheet")

    # Adding arguments for each parser
    # tonii
    nii.add_argument("input", help=input_str, type=str)
    nii.add_argument("-b", "--bids", help=bids_opt, action=argparse.BooleanOptionalAction,
                     default=False)
    nii.add_argument("-o", "--output", help=output_fnm_str, type=str, default=None)
    nii.add_argument("-s", "--scanid", help="Scan ID, option to specify a particular scan to "
                                            "convert (default: convert every scan)", type=str)
    nii.add_argument("-r", "--recoid", help="RECO ID, option to specify a particular "
                                            "reconstruction id to convert; only read together "
                                            "with -s, since without it every reconstruction of "
                                            "every scan is converted (default: 1)",
                     type=int, default=1)
    nii.add_argument("-t", "--subjecttype", help=subjtype_opt, type=str, default=None)
    nii.add_argument("-p", "--position", help=position_opt, type=str, default=None)
    nii.add_argument("--ignore-slope", help=slope_opt, action=argparse.BooleanOptionalAction,
                     default=False)
    nii.add_argument("--ignore-offset", help=offset_opt, action=argparse.BooleanOptionalAction,
                     default=False)
    nii.add_argument("--ignore-rescale", help=rescale_opt, action=argparse.BooleanOptionalAction,
                     default=False)
    nii.add_argument("--ignore-localizer", help=localizer_opt,
                     action=argparse.BooleanOptionalAction, default=True)

    # tonii_all
    niiall.add_argument("input", help=input_dir_str, type=str)
    niiall.add_argument("-o", "--output", help=output_dir_str, type=str, default='Data')
    niiall.add_argument("-b", "--bids", help=bids_opt, action=argparse.BooleanOptionalAction,
                        default=False)
    niiall.add_argument("-t", "--subjecttype", help=subjtype_opt, type=str, default=None)
    niiall.add_argument("-p", "--position", help=position_opt, type=str, default=None)
    niiall.add_argument("--ignore-slope", help=slope_opt, action=argparse.BooleanOptionalAction,
                        default=False)
    niiall.add_argument("--ignore-offset", help=offset_opt, action=argparse.BooleanOptionalAction,
                        default=False)
    niiall.add_argument("--ignore-rescale", help=rescale_opt,
                        action=argparse.BooleanOptionalAction, default=False)
    niiall.add_argument("--ignore-localizer", help=localizer_opt,
                        action=argparse.BooleanOptionalAction, default=True)

    # bids_helper
    bids_helper.add_argument("input", help=input_dir_str, type=str)
    bids_helper.add_argument("output", help="output BIDS datasheet filename", type=str)
    bids_helper.add_argument("-f", "--format", help="file format of BIDS datasheets. Use this "
                                                    "option if you did not specify the extension "
                                                    "on output (default: csv)",
                             type=str, choices=('csv', 'tsv'), default='csv')
    bids_helper.add_argument("-j", "--json", help="create JSON syntax template for parsing "
                                                  "metadata from the header "
                                                  "(default: no template)",
                             action=argparse.BooleanOptionalAction, default=False)
    # Long-only on purpose: -s and -t mean --scanid and --subjecttype in the converting
    # sub-commands, and one letter must not mean two things.
    bids_helper.add_argument("--subj", help="switch subject and study IDs "
                                            "(default: keep the recorded subject ID)",
                             action=argparse.BooleanOptionalAction, default=False)
    bids_helper.add_argument("--sess", help="switch session and study ID "
                                            "(default: keep the recorded session ID)",
                             action=argparse.BooleanOptionalAction, default=False)

    # bids_convert
    bids_convert.add_argument("input", help=input_dir_str, type=str)
    bids_convert.add_argument("datasheet", help="input BIDS datahseet filename", type=str)
    bids_convert.add_argument("-j", "--json", help="input JSON syntax template filename "
                                                   "(default: none, the sidecars carry only what "
                                                   "the converter derives)", type=str, default=None)
    bids_convert.add_argument("-o", "--output", help=output_dir_str, type=str, default='Data')
    bids_convert.add_argument("-t", "--subjecttype", help=subjtype_opt, type=str, default=None)
    bids_convert.add_argument("-p", "--position", help=position_opt, type=str, default=None)
    bids_convert.add_argument("--ignore-slope", help=slope_opt,
                              action=argparse.BooleanOptionalAction, default=False)
    bids_convert.add_argument("--ignore-offset", help=offset_opt,
                              action=argparse.BooleanOptionalAction, default=False)
    bids_convert.add_argument("--ignore-rescale", help=rescale_opt,
                              action=argparse.BooleanOptionalAction, default=False)

    args = parser.parse_args()

    if args.function == 'info':
        path = args.input
        if any([os.path.isdir(path), ('zip' in path), ('PvDataset' in path)]):
            study = BrukerLoader(path)
            study.info()
        else:
            list_path = [d for d in os.listdir('.') if (any([os.path.isdir(d),
                                                             ('zip' in d),
                                                             ('PvDataset' in d)]) and re.search(path, d, re.IGNORECASE))]
            for p in list_path:
                study = BrukerLoader(p)
                study.info()


    elif args.function == 'tonii':
        path     = args.input
        scan_id  = args.scanid
        reco_id  = args.recoid
        study    = BrukerLoader(path)
        scale_mode = set_rescale(args)
        ignore_localizer = args.ignore_localizer
        study = override_header(study, args.subjecttype, args.position)
        
        if study.is_pvdataset:
            if args.output:
                output = args.output
            elif study.subj_id is not None:
                output = f'{study.subj_id}_{study.study_id}'
            else:
                # standalone scan without a subject file: name after the input dir
                output = os.path.basename(os.path.normpath(path))
            if scan_id:
                scanname = str(get_value(study.get_acqp(int(scan_id)), 'ACQ_scan_name'))
                scanname = scanname.replace(' ','-')
                output_fname = f'{output}-{scan_id}-{reco_id}-{scanname}'
                scan_id = int(scan_id)
                reco_id = int(reco_id)
                
                if ignore_localizer and is_localizer(study, scan_id, reco_id):
                    print(f'Identified a localizer, the file will not be converted: ScanID:{scan_id!s}')
                else:
                    try:
                        study.save_as(scan_id, reco_id, output_fname, scale_mode=scale_mode)
                        save_meta_files(study, args, scan_id, reco_id, output_fname)
                        print(f'NifTi file is generated... [{output_fname}]')
                    except Exception as e:
                        report_conversion_error(scan_id, reco_id, e)
            else:
                for scan_id, recos in study.avail_reco_id.items():
                    scanname = str(get_value(study.get_acqp(int(scan_id)), 'ACQ_scan_name'))
                    scanname = scanname.replace(' ','-')
                    if ignore_localizer and is_localizer(study, scan_id, recos[0]):
                        print(f'Identified a localizer, the file will not be converted: ScanID:{scan_id!s}')
                    else:
                        for reco_id in recos:
                            output_fname = f'{output}-{str(scan_id).zfill(2)}-{reco_id}-{scanname}'
                            try:
                                study.save_as(scan_id, reco_id, output_fname, scale_mode=scale_mode)
                                save_meta_files(study, args, scan_id, reco_id, output_fname)
                                print(f'NifTi file is generated... [{output_fname}]')
                            except Exception as e:
                                report_conversion_error(scan_id, reco_id, e)
        else:
            print(f'{path} is not PvDataset.')

    elif args.function == 'tonii_all':
        from os.path import isdir, isfile
        from os.path import join as opj

        path = args.input
        scale_mode = set_rescale(args)
        ignore_localizer = args.ignore_localizer
        invalid_error_message = f'[Error] Invalid input path: {path}\n'
        empty_folder = '        The input path does not contain any raw data.'
        wrong_target = '        The input path indicates raw data itself. \n' \
                       '        You must input the parents folder instead of path of the raw data\n' \
                       '        If you want to convert single session raw data, use (tonii) instead.'

        list_of_raw = sorted([d for d in os.listdir(path) if isdir(opj(path, d)) \
                              or (isfile(opj(path, d)) and (('zip' in d) or ('PvDataset' in d)))])
        if not len(list_of_raw):
            # raise error with message if the folder is empty (or does not contains any PvDataset)
            print(invalid_error_message, empty_folder)
            raise InvalidApproach(invalid_error_message)
        if BrukerLoader(path).is_pvdataset:
            # raise error if the input path is identified as PvDataset
            print(invalid_error_message, wrong_target)
            raise InvalidApproach(invalid_error_message)

        base_path = args.output
        mkdir(base_path)
        for raw in list_of_raw:
            sub_path = os.path.join(path, raw)
            study = BrukerLoader(sub_path)
            if study.is_pvdataset:
                study = override_header(study, args.subjecttype, args.position)
                if len(study.avail_scan_id):
                    subj_path = os.path.join(base_path, f'sub-{study.subj_id}')
                    mkdir(subj_path)
                    sess_path = os.path.join(subj_path, f'ses-{study.study_id}')
                    mkdir(sess_path)
                    for scan_id, recos in study.avail_reco_id.items():
                        method = scanMethod(study, scan_id)
                        if method is None:
                            # A scan can carry reconstruction data (2dseq) without a
                            # method file (e.g. an adjustment/reference scan). Skip it
                            # rather than fail on the method lookup below.
                            print(f'ScanID:{scan_id} has no method file; skipping.')
                            continue
                        if ignore_localizer and is_localizer(study, scan_id, recos[0]): # add option to exclude localizer during mass conversion
                            print(f'Identified a localizer, the file will not be converted: ScanID:{scan_id!s}')
                        else:
                            if re.search('epi', method, re.IGNORECASE) and not re.search('dti', method, re.IGNORECASE):
                                output_path = os.path.join(sess_path, 'func')
                            elif re.search('dti', method, re.IGNORECASE):
                                output_path = os.path.join(sess_path, 'dwi')
                            elif re.search('flash', method, re.IGNORECASE) or re.search('rare', method, re.IGNORECASE):
                                output_path = os.path.join(sess_path, 'anat')
                            else:
                                output_path = os.path.join(sess_path, 'etc')
                            mkdir(output_path)
                            filename = f'sub-{study.subj_id}_ses-{study.study_id}_{str(scan_id).zfill(2)}'
                            for reco_id in recos:
                                output_fname = os.path.join(output_path, f'{filename}_reco-{str(reco_id).zfill(2)}')
                                try:
                                    study.save_as(scan_id, reco_id, output_fname, scale_mode=scale_mode)
                                    save_meta_files(study, args, scan_id, reco_id, output_fname)
                                except Exception as e:
                                    report_conversion_error(scan_id, reco_id, e)
                    print(f'{raw} is converted...')
                else:
                    print(f'{raw} does not contains any scan data to convert...')
            else:
                print(f'{raw} is not PvDataset.')

    elif args.function == 'bids_helper':
        import pandas as pd
        path = os.path.abspath(args.input)
        ds_output = os.path.abspath(args.output)
        make_json = args.json
        swap_id = args.subj
        swap_sess = args.sess

        if swap_id and swap_sess:
            warnings.warn('\nBoth switch subject/study IDs and switch session/study ID options are on. You probably do not want this!\n')

        # [220202] for back compatibility
        ds_fname, ds_output_ext = os.path.splitext(ds_output)
        if ds_output_ext in ['.csv', '.tsv']:
            # infer format from extension
            ds_format = ds_output_ext[1:]
        else:
            ds_format = args.format

        # [220202] make compatible with csv and tsv
        output = f'{ds_fname}.{ds_format}' 

        Headers = ['RawData', 'SubjID', 'SessID', 'ScanID', 'RecoID', 'DataType',
                   'task', 'acq', 'ce', 'rec', 'dir', 'run', 'inv', 'flip', 'mt', 'part', 'modality',
                   'b0group', 'Start', 'End']
        df = pd.DataFrame(columns=Headers)

        # if the path directly contains scan files for one participant
        if 'subject' in os.listdir(path):
            dNames = ['']
        else:         # old way, when you run against the parent folder (which contains one or more scan folder).
            dNames = sorted(os.listdir(path))

        for dname in dNames:
            dpath = os.path.join(path, dname)

            try:
                dset = BrukerLoader(dpath)
            except Exception:
                dset = None

            if dset is not None and dset.is_pvdataset:
                rawdata = dset.path

                if swap_id:
                    subj_id = dset.study_id
                else:
                    subj_id = dset.subj_id

                if swap_sess:
                    sess_id = dset.study_id
                else:
                    sess_id = dset.session_id

                # make subj_id bids appropriate
                subj_id = cleanSubjectID(subj_id)

                # make sess_id bids appropriate
                sess_id = cleanSessionID(sess_id)

                for scan_id, recos in dset.avail_reco_id.items():
                    method = scanMethod(dset, scan_id)
                    if method is None:
                        # Reconstruction data with no method file (e.g. an
                        # adjustment/reference scan): can't be classified, so skip
                        # it rather than fail on the method lookup below.
                        warnings.warn(f'ScanID:[{scan_id}] has no method file; skipping.')
                        continue
                    for reco_id in recos:
                        visu_pars = dset.get_visu_pars(scan_id, reco_id)
                        if (dset._get_dim_info(visu_pars)[1] == 'spatial_only'
                                and not is_localizer(dset, scan_id, reco_id)):
                            datatype = assignDataType(method)

                            # A derived reconstruction is a STACK, not an image: an
                            # ISA fit writes five volumes and a DTI reconstruction
                            # twenty-two, each index meaning something different.
                            # Converting one whole is what produced the old invalid
                            # output (a single-frame "MESE" with no echo-/EchoTime, a
                            # "dwi" whose bval/bvec length did not match the volumes).
                            #
                            # An ISA fit does contain one volume BIDS has a suffix
                            # for -- the relaxation time -- so it is named here and
                            # the converter extracts it. Everything else derived
                            # stays 'etc' and is routed out of the validated tree.
                            derived_map = None
                            groups = dset.get_frame_groups(scan_id, reco_id)
                            if derived.is_derived(groups):
                                found = derived.isa_map(visu_pars)
                                if found:
                                    _, derived_map, _ = found
                                    datatype = 'anat'
                                else:
                                    datatype = 'etc'
                                    warnings.warn(
                                        f'ScanID:[{scan_id}] RecoID:[{reco_id}] is a derived '
                                        'reconstruction with no single BIDS suffix (tensor or '
                                        'unrecognised fit); it goes to derivatives/.')

                            # ASL / perfusion (FAIR, (p)CASL, PASL, ...) is
                            # neither BOLD nor anatomical; it belongs in BIDS
                            # perf/asl, which is not emitted here. Leave it
                            # unclassified rather than mislabel it.
                            # ASL is neither BOLD nor anatomical. Keyed off the
                            # method name only, and checked before the epi->func
                            # branch, because FAIR_EPI and CASL_EPI both contain
                            # 'epi' and FAIR_RARE reads as 'rare'.
                            elif asl.labeling_type(method):
                                datatype = 'perf'

                            # A BOLD time-series needs >1 volume; a single-
                            # repetition EPI is not bold (BIDS BOLD_NOT_4D).
                            # Leave it unclassified so the user can decide.
                            elif datatype == 'func' and numRepetitions(dset, scan_id) <= 1:
                                datatype = 'etc'
                                warnings.warn(f'ScanID:[{scan_id}] is a single-volume EPI '
                                              '(PVM_NRepetitions<=1), not a BOLD time-series. '
                                              'Marked as "etc"; set DataType/modality in the '
                                              'datasheet to convert it.')

                            item = dict(zip(Headers, [rawdata, subj_id, sess_id, scan_id, reco_id, datatype]))

                            # BIDS requires a task- entity and TaskName for func;
                            # prefill from the Bruker protocol name (user-editable)
                            # so func output validates by default.
                            if datatype == 'func':
                                item['task'] = bidsTaskLabel(visu_pars)

                            if datatype == 'fmap':
                                for m, s, e in [['fieldmap', 0, 1], ['magnitude', 1, 2]]:
                                    item['modality'] = m
                                    item['Start'] = s
                                    item['End'] = e
                                    df = pd.concat([df, pd.DataFrame([item])], ignore_index=True)
                            elif datatype == 'perf':
                                item['modality'] = 'asl'
                                df = pd.concat([df, pd.DataFrame([item])], ignore_index=True)
                            elif datatype == 'dwi':
                                item['modality'] = 'dwi'
                                df = pd.concat([df, pd.DataFrame([item])], ignore_index=True)
                            elif derived_map:
                                # Checked before the MSME branch: an ISA T2 map is
                                # usually fitted FROM an MSME scan, so matching on the
                                # method would relabel the map as MESE/T2w.
                                item['modality'] = derived_map
                                df = pd.concat([df, pd.DataFrame([item])], ignore_index=True)
                            elif datatype == 'anat' and re.search('MSME', method, re.IGNORECASE):
                                # MSME is multi-slice multi-echo, but only a
                                # genuinely multi-echo reconstruction is a BIDS
                                # MESE (which requires an echo- entity). A
                                # single-echo MSME is just a T2-weighted image.
                                item['modality'] = ('MESE'
                                                    if dset.is_multi_echo(scan_id, reco_id)
                                                    else 'T2w')
                                df = pd.concat([df, pd.DataFrame([item])], ignore_index=True)
                            else:
                                df = pd.concat([df, pd.DataFrame([item])], ignore_index=True)
        # -f is restricted to csv/tsv by argparse, and the extension branch above only
        # ever sets one of the two, so there is no third case to reject here.
        df.to_csv(output, index=None, sep=',' if ds_format == 'csv' else '\t')

        if make_json:
            # Imported here rather than at module scope: loading the BIDS schema costs a
            # 589 KB JSON parse, and only the BIDS sub-commands need it.
            from ..lib.bids import BIDS_VERSION

            json_fname = f'{ds_fname}.json'
            print('Creating JSON syntax template for parsing the BIDS required metadata '
                  f'(BIDS v{BIDS_VERSION}): {json_fname}')
            with open(json_fname, 'w') as f:
                import json

                from ..lib.reference import (
                    COMMON_META_REF,
                    FIELDMAP_META_REF,
                    FMRI_META_REF,
                )
                ref_dict = {'common': COMMON_META_REF,
                                'func': FMRI_META_REF,
                                'fmap': FIELDMAP_META_REF}
                json.dump(ref_dict, f, indent=4)

        print('[Important notice] The function helps to minimize the BIDS organization but does not guarantee that '
              'the dataset always meets the BIDS requirements. '
              'Therefore, after converting your data, we recommend validating '
              'your dataset using an official BIDS validator.')

    elif args.function == 'bids_convert':
        import pandas as pd

        from ..lib.utils import bids_validation, build_bids_json
        
        pd.options.mode.chained_assignment = None
        path = args.input
        datasheet = args.datasheet
        root_path = args.output
        datasheet_ext = os.path.splitext(datasheet)[-1]

        # [220202] make compatible with csv and tsv
        if 'csv' in datasheet_ext:
            df = pd.read_csv(datasheet, dtype={'SubjID': str, 'SessID': str, 'run': str}, index_col=None, header=0, sep=',')
        elif 'tsv' in datasheet_ext:
            df = pd.read_csv(datasheet, dtype={'SubjID': str, 'SessID': str, 'run': str}, index_col=None, header=0, sep='\t')
        else:
            print(f'{datasheet_ext} if not supported format.')
            raise InvalidApproach('Invalid input for datasheet!')
            
        json_fname = args.json
        scale_mode = set_rescale(args)

        # check if the project is session included
        if all(pd.isnull(df['SessID'])):
            # SessID was removed (not column, but value), this need to go to documentation
            include_session = False
        else:
            # if SessionID appears in datasheet, then by default session appears.
            include_session = True

        mkdir(root_path)

        # prepare the required file for converted BIDS dataset
        generateModalityAgnosticFiles(root_path, json_fname)

        # Rows for the modality-agnostic tables, collected while converting and
        # written once at the end: a subject's row is only correct after its scans
        # are known, and _scans.tsv needs the filenames the converter chose.
        participant_rows = []
        session_rows = {}        # subject label -> [session row, ...]
        scan_rows = {}           # (subject label, session label or None) -> [row, ...]

        print('Inspect input BIDS datasheet...')

        # if the path directly contains scan files for one participant
        if 'subject' in os.listdir(path):
            dNames = ['']
        else:         # old way, when you run against the parent folder (which contains one or more scan folder).
            dNames = sorted(os.listdir(path))

        for dname in dNames:
            dpath = os.path.join(path, dname)
            try:
                dset = BrukerLoader(dpath)
                dset = override_header(dset, args.subjecttype, args.position)
                if dset.is_pvdataset:
                    rawdata = dset.path
                    filtered_dset = df[df['RawData'].isin([rawdata])].reset_index()

                    # add Filename and Dir columns (object dtype to hold path strings)
                    filtered_dset['FileName'] = pd.Series([None] * len(filtered_dset),
                                                          index=filtered_dset.index, dtype=object)
                    filtered_dset['Dir'] = pd.Series([None] * len(filtered_dset),
                                                     index=filtered_dset.index, dtype=object)

                    if len(filtered_dset):
                        subj_id = next(iter(set(filtered_dset['SubjID'])))
                        subj_code = f'sub-{subj_id}'

                        filtered_dset = completeFieldsCreateFolders(df, filtered_dset, dset, include_session, root_path, subj_code)

                        list_tested_fn = []
                        # Converting data according to the updated sheet
                        print(f'Converting {dname}...')

                        for i, row in filtered_dset.iterrows():
                            if pd.isnull(row.FileName) or pd.isnull(row.modality):
                                # No valid BIDS suffix, so it must not enter the
                                # validated tree -- but dropping it loses the scan.
                                # It goes to derivatives/ or sourcedata/ instead,
                                # both of which the validator ignores by definition.
                                try:
                                    convertUnvalidated(root_path, dset, row, subj_code,
                                                       include_session, scale_mode)
                                except Exception as e:
                                    report_conversion_error(row.ScanID, row.RecoID, e)
                                continue
                            temp_fname = f'{row.FileName}_{row.modality}'
                            if temp_fname not in list_tested_fn:
                                try:
                                    # filter the DataFrame that has same filename (updated without run)
                                    fn_filter = filtered_dset.loc[:, 'FileName'].isin([row.FileName])
                                    fn_df = filtered_dset[fn_filter].reset_index(drop=True)

                                    # filter specific modality from above DataFrame
                                    md_filter = fn_df.loc[:, 'modality'].isin([row.modality])
                                    md_df = fn_df[md_filter].reset_index(drop=True)

                                    if len(md_df) > 1:
                                        conflict_tested = []
                                        for j, sub_row in md_df.iterrows():
                                            if pd.isnull(sub_row.run):
                                                fname = f'{sub_row.FileName}_run-{str(j+1).zfill(2)}'
                                            else:
                                                _ = bids_validation(df, i, 'run', sub_row.run, 3, dtype=int)
                                                fname = f'{sub_row.FileName}_run-{str(sub_row.run).zfill(2)}' # [20210822] format error
                                            if fname in conflict_tested:
                                                raise ValueConflictInField(f'ScanID:[{sub_row.ScanID}] Conflict error. '
                                                                           'The [run] index value must be unique '
                                                                           'among the scans with the same modality.')
                                            else:
                                                conflict_tested.append(fname)
                                            recordScanRows(
                                                scan_rows, root_path, dset, sub_row, include_session,
                                                build_bids_json(dset, sub_row, fname, json_fname,
                                                                scale_mode=scale_mode))
                                    else:
                                        fname = f'{row.FileName}'
                                        recordScanRows(
                                            scan_rows, root_path, dset, row, include_session,
                                            build_bids_json(dset, row, fname, json_fname,
                                                            scale_mode=scale_mode))
                                    list_tested_fn.append(temp_fname)
                                except Exception as e:
                                    # One scan failing to convert must not abort the whole
                                    # study's BIDS conversion (mirrors tonii_all's per-scan
                                    # guard). Report it and move on to the next scan.
                                    report_conversion_error(row.ScanID, row.RecoID, e)

                        # Record the participant only if at least one scan actually
                        # converted; otherwise participants.tsv would list a subject
                        # with no data (BIDS PARTICIPANT_ID_MISMATCH).
                        if list_tested_fn:
                            recordParticipant(participant_rows, session_rows, dset,
                                              subj_code, filtered_dset, include_session)
                        print('...Done.')
            except FileNotValidError:
                pass

        writeFieldmapLinks(root_path, scan_rows)
        writeParticipantTables(root_path, participant_rows, session_rows, scan_rows)
    else:
        parser.print_help()


def report_conversion_error(scan_id, reco_id, error):
    """Print a skip notice for non-image data, or a failure notice otherwise."""
    if 'non-image data' in str(error):
        print(f'Skipped (non-image data): ScanID:{scan_id}, RecoID:{reco_id}')
    else:
        print(f'Conversion failed: ScanID:{scan_id}, RecoID:{reco_id} ({error})')


def cleanSubjectID(subj_id):
    """To replace the underscore in subject id.
    Args:
        subj_id (str): the orignal subject id.
    Returns:
        str: the replaced subject id.
    """


    subj_id = str(subj_id)
    
    # underscore will mess up bids output
    if '_' in subj_id:
        subj_id = subj_id.replace('_', 'Underscore')
        # warn user that the subject/participantID has a '_' and is replaced with 'Underscore'
        warnings.warn('Participant or subject ID has "_"s, replaced with "Underscore" to make it bids compatiable. You should avoid use "_" in participant/subject ID for BIDS purpose')

    # Hyphen will mess up bids output
    if '-' in subj_id:
        subj_id = subj_id.replace('-', 'Hyphen')
        # warn user that the subject/participantID has a '-' and is replaced with 'Hyphen'
        warnings.warn('Participant or subject ID has "-"s, replaced with "Hyphen" to make it bids compatiable. You should avoid use "-" in participant/subject ID for BIDS purpose')

    # A BIDS label must be alphanumeric; drop any remaining special characters
    # (e.g. the '.' in a version-derived id like '3.7'), which are invalid in a
    # sub-<label> and make every file under the subject unrecognizable to the
    # BIDS validator.
    cleaned = re.sub(r'[^a-zA-Z0-9]', '', subj_id)
    if cleaned != subj_id:
        warnings.warn('Participant or subject ID had non-alphanumeric characters; '
                      'removed to make it BIDS compatible. Avoid special characters '
                      'in participant/subject IDs.')
        subj_id = cleaned
    return subj_id


# This could integrate with cleanSubjectID, but mind the different warning messages
def cleanSessionID(sess_id):
    """To replace the underscore in session id.
    Args:
        sess_id (str): the orignal session id.
    Returns:
        str: the replaced session id.
    """

    
    sess_id = str(sess_id)

    # underscore will mess up bids output
    if '_' in sess_id:
        sess_id = sess_id.replace('_', 'Underscore')
        # warn user that the subject/participantID has a '_' and is replaced with 'Underscore'
        warnings.warn('Session ID has "_"s, replaced with "Underscore" to make it bids compatiable. You should avoid use "_" in session ID for BIDS purpose')

    # Hyphen will mess up bids output
    if '-' in sess_id:
        sess_id = sess_id.replace('-', 'Hyphen')
        # warn user that the subject/participantID has a '-' and is replaced with 'Hyphen'
        warnings.warn('Session ID has "-"s, replaced with "Hyphen" to make it bids compatiable. You should avoid use "-" in session ID for BIDS purpose')

    # A BIDS label must be alphanumeric; drop any remaining special characters
    # (e.g. a '.' in a version-derived id), invalid in a ses-<label>.
    cleaned = re.sub(r'[^a-zA-Z0-9]', '', sess_id)
    if cleaned != sess_id:
        warnings.warn('Session ID had non-alphanumeric characters; removed to make '
                      'it BIDS compatible. Avoid special characters in session IDs.')
        sess_id = cleaned

    return sess_id


def bidsTaskLabel(visu_pars):
    """A BIDS task label (alphanumeric only) derived from the Bruker protocol name.

    func data must carry a ``task-`` entity; deriving it from the acquisition
    protocol gives an accurate, user-overridable default.
    """
    proto = (get_value(visu_pars, 'VisuAcquisitionProtocol')
             or get_value(visu_pars, 'VisuAcqSequenceName') or 'task')
    label = re.sub(r'[^0-9a-zA-Z]', '', str(proto))
    return label or 'task'


def scanMethod(dset, scan_id):
    """The Bruker method name of a scan, or None when it has no method file.

    A scan can carry reconstruction data without a method file (an adjustment
    or reference scan); it cannot be classified and is skipped. A method file
    that is present but unreadable is a different problem and is not hidden
    here.
    """
    name = get_value(dset.get_method(scan_id), 'Method')
    return None if name is None else str(name)


def numRepetitions(dset, scan_id):
    """Number of temporal repetitions (volumes) for a scan; 1 when unknown."""
    try:
        nr = get_value(dset.get_method(scan_id), 'PVM_NRepetitions', 1)
        return int(nr) if nr is not None else 1
    except Exception:
        return 1


def assignDataType (method):
    """To assign the dataType based on method.
    Args:
        method (str): the Bruker method name (see scanMethod).
    Returns:
        str: the datatype.
    """
    if re.search('epi', method, re.IGNORECASE) and not re.search('dti', method, re.IGNORECASE):
        #Why epi is function here? there should at lease a comment.
        datatype = 'func'
    elif re.search('dti', method, re.IGNORECASE):
        datatype = 'dwi'
    elif re.search('flash', method, re.IGNORECASE) or re.search('rare', method, re.IGNORECASE):
        datatype = 'anat'
    elif re.search('fieldmap', method, re.IGNORECASE):
        datatype = 'fmap'
    elif re.search('MSME', method, re.IGNORECASE):
        datatype = 'anat'

        # warn user for MSME default to anat and MESE
        import warnings
        msg = "MSME found in your scan, default to anat DataType and MESE modality, " + \
        "please update the datasheet to indicate the proper DataType if different than default." 
        warnings.warn(msg)

    else:
        # what is this? seems like holding files not able to identify
        datatype = 'etc'

        # warn user to manually update the DataType in datasheet
        import warnings
        
        msg = "\n \n ----- Important ----- \
        \n We do not know how to classify some of your scan and marked them as etc.\
        \n To produce valid BIDS outputs, please update the datasheet to indicate the proper DataType for them \n"
        warnings.warn(msg)

    return datatype


def generateModalityAgnosticFiles(root_path, json_fname):
    """To create ModalityAgnosticFiles in output folder.
    Args:
        root_path (str): the root output folder
        json_fname (str): I do not under why this variable is needed.
    Returns:
        nothing: just generate files.
    """
    import datetime
    import json
    from copy import deepcopy

    from ..lib.bids import BIDS_VERSION
    from ..lib.reference import DATASET_DESC_REF

    data_des = os.path.join(root_path, 'dataset_description.json')
    readme = os.path.join(root_path, 'README')
    changes = os.path.join(root_path, 'CHANGES')

    if not os.path.exists(data_des):
        desc = deepcopy(DATASET_DESC_REF)
        # Assigning an existing key keeps its position, so BIDSVersion stays second.
        desc['BIDSVersion'] = BIDS_VERSION
        # Record BrkRaw-legacy as the generator (BIDS recommended provenance).
        desc['GeneratedBy'] = [{'Name': 'BrkRaw-legacy',
                                    'Version': __version__,
                                    'CodeURL': 'https://github.com/gdevenyi/brkraw-legacy'}]
        # Drop empty placeholders so the sidecar only ships meaningful values.
        desc = {k: v for k, v in desc.items() if v not in ('', [], {})}
        with open(data_des, 'w') as f:
            json.dump(desc, f, indent=4)
    if not os.path.exists(readme):
        with open(readme, 'w') as f:
            f.write(f'This dataset was converted using BrkRaw (v{__version__}) on '
                    f'{datetime.datetime.now().astimezone().isoformat()}.\n')
            f.write('\n## Acquisition times\n'
                    'The `acq_time` columns hold the scanner clock as recorded, not a\n'
                    'shifted one. If you are sharing this dataset, shift the dates\n'
                    'first -- BIDS asks for that, and a converter cannot do it for you\n'
                    'without destroying the timing you may still need.\n')
            f.write('\n## Species\n'
                    'The `species` column is `n/a`: ParaVision records a body plan\n'
                    '(Biped/Quadruped/Phantom), never a binomial name. Fill it in --\n'
                    'BIDS reads an absent species as `homo sapiens`.\n')
            f.write('\n## How to cite?\n - https://doi.org/10.5281/zenodo.3818615\n')
    if not os.path.exists(changes):
        with open(changes, 'w') as f:
            f.write(f'1.0.0 {datetime.datetime.now().astimezone().date().isoformat()}\n'
                    f' - Dataset created with BrkRaw v{__version__}.\n')

    # participants.tsv and participants.json are deliberately NOT written here.
    # Both are written after conversion by writeParticipantTables, and only when
    # there is a participant to record: a study whose every scan is unclassifiable
    # produces no rows at all, and a sidecar written up front would then be left
    # describing a table that does not exist (SIDECAR_WITHOUT_DATAFILE).



def convertUnvalidated(root_path, dset, row, subj_code, include_session, scale_mode):
    """Convert a scan that has no valid BIDS datatype, outside the validated tree.

    Two destinations, because they are two different things. A ParaVision-computed
    stack with no single BIDS suffix -- a DTI tensor reconstruction, an unrecognised
    fit -- is a derivative. A scan we simply could not classify is not derived at
    all; it is source data we are declining to interpret.

    Both directories are ignored by the validator by definition, so the data is kept
    without costing an error. Naming inside them is ours, so it is the plainest thing
    that stays traceable to the scan it came from.
    """
    import pandas as pd

    from ..lib import derived

    try:
        groups = dset.get_frame_groups(row.ScanID, row.RecoID)
    except Exception:
        groups = []
    if derived.is_derived(groups):
        base = os.path.join(root_path, 'derivatives', 'brkraw-legacy')
        writeDerivativesDescription(base)
    else:
        base = os.path.join(root_path, 'sourcedata')

    parts = [subj_code]
    if include_session and pd.notnull(row.SessID):
        parts.append(f'ses-{row.SessID}')
    directory = os.path.join(base, *parts)
    mkdir(directory)
    stem = '_'.join([*parts, f'scan-{row.ScanID}', f'reco-{row.RecoID}'])

    niiobj = dset.get_niftiobj(row.ScanID, row.RecoID, scale_mode=scale_mode)
    for i, nii in enumerate(niiobj if isinstance(niiobj, list) else [niiobj]):
        name = f'{stem}_chunk-{str(i + 1).zfill(2)}' if isinstance(niiobj, list) and \
            len(niiobj) > 1 else stem
        nii.to_filename(os.path.join(directory, f'{name}.nii.gz'))


def writeDerivativesDescription(base):
    """The dataset_description.json a derivatives directory needs to stand alone."""
    import json

    from ..lib.bids import BIDS_VERSION

    mkdir(base)
    path = os.path.join(base, 'dataset_description.json')
    if os.path.exists(path):
        return
    with open(path, 'w') as f:
        json.dump({
            'Name': 'BrkRaw-legacy derived reconstructions',
            'BIDSVersion': BIDS_VERSION,
            'DatasetType': 'derivative',
            'GeneratedBy': [{'Name': 'BrkRaw-legacy', 'Version': __version__,
                             'CodeURL': 'https://github.com/gdevenyi/brkraw-legacy'}],
        }, f, indent=4)


def recordScanRows(scan_rows, root_path, dset, row, include_session, written):
    """Note each written image in the ``_scans.tsv`` rows for its subject/session.

    One datasheet row can become several files -- multi-echo and multi-slicepack
    both split -- so the converter has to say what it actually wrote.
    """
    import pandas as pd

    from ..lib import tabular

    if not written:
        return
    subject = f'sub-{row.FileName.split("_")[0].replace("sub-", "", 1)}'
    session = f'ses-{row.SessID}' if (include_session and pd.notnull(row.SessID)) else None
    # `filename` is relative to the directory holding the table, which is the
    # session directory when there is one and the subject directory otherwise.
    base = os.path.join(root_path, subject, session) if session \
        else os.path.join(root_path, subject)
    try:
        acquired = tabular.acq_time(dset.get_visu_pars(row.ScanID, row.RecoID))
    except Exception:
        acquired = None
    for path in written:
        scan_rows.setdefault((subject, session), []).append({
            'filename': os.path.relpath(path, base).replace(os.sep, '/'),
            'acq_time': acquired,
            # The datasheet's say on which fieldmap covers this scan, if given.
            'b0group': row.b0group if ('b0group' in row and pd.notnull(row.b0group)) else None,
        })


def recordParticipant(participant_rows, session_rows, dset, subj_code, filtered_dset,
                      include_session):
    """Note one converted subject, and its sessions when the dataset has any."""
    from ..lib import tabular

    subject = dset.subject
    participant_rows.append(tabular.participant_row(subject, subj_code))
    # The taxon comes from the subject frame the scan was acquired in, read per
    # scan -- never from the study `subject` file, which says Human on every PV5.1
    # study regardless of specimen.
    converted = filtered_dset.dropna(subset=['FileName'])
    if len(converted):
        first = converted.iloc[0]
        try:
            visu_pars = dset.get_visu_pars(first.ScanID, first.RecoID)
        except Exception:
            visu_pars = None
        if tabular.is_non_human(visu_pars):
            warnings.warn(
                f'{subj_code}: acquired in the rodent (quadruped) subject frame, so '
                'the subject is not human -- but ParaVision records no species name. '
                'BIDS reads an absent species as "homo sapiens", so set the species '
                'column in participants.tsv before sharing this dataset.')
    if include_session:
        acquired = tabular.session_date(subject)
        for sess_id in filtered_dset['SessID'].dropna().unique():
            rows = session_rows.setdefault(subj_code, [])
            label = f'ses-{sess_id}'
            if not any(r['session_id'] == label for r in rows):
                rows.append({'session_id': label, 'acq_time': acquired})


def writeFieldmapLinks(root_path, scan_rows):
    """Link each fieldmap to the images it corrects, in both BIDS mechanisms.

    Run after conversion because it needs the final filenames: run- indices are
    only resolved while converting, and IntendedFor has to name what was written.

    Two mechanisms on purpose. `B0FieldIdentifier`/`B0FieldSource` pair by name and
    survive a rename, which is the spec's current answer; `IntendedFor` is a path
    list and is still what most tools read.
    """
    from ..lib import bids

    for (subject, session), rows in scan_rows.items():
        directory = os.path.join(root_path, subject, session) if session \
            else os.path.join(root_path, subject)
        pairs = bids.pair_fieldmaps(rows)
        for index, (fieldmap, targets) in enumerate(sorted(pairs.items()), start=1):
            if not targets:
                warnings.warn(f'{fieldmap}: no image follows this fieldmap that it could '
                              'correct, so it is left unlinked. Set b0group in the '
                              'datasheet if it belongs to a scan acquired before it.')
                continue
            identifier = next((r.get('b0group') for r in rows
                               if r['filename'] == fieldmap and r.get('b0group')), None)
            identifier = identifier or f'b0map{index}'
            # IntendedFor is participant-relative, so it carries the session.
            prefix = f'{session}/' if session else ''
            _patchSidecar(directory, fieldmap, {
                'B0FieldIdentifier': identifier,
                'IntendedFor': [f'{prefix}{t}' for t in targets],
            })
            for target in targets:
                _patchSidecar(directory, target, {'B0FieldSource': identifier})


def _patchSidecar(directory, nifti_relpath, fields):
    """Merge `fields` into the sidecar of `nifti_relpath`, if it has one."""
    import json

    path = os.path.join(directory, nifti_relpath).replace('.nii.gz', '.json')
    if not os.path.exists(path):
        # magnitude images are written without a sidecar, by design
        return
    with open(path) as f:
        sidecar = json.load(f)
    sidecar.update(fields)
    with open(path, 'w') as f:
        json.dump(sidecar, f, indent=4)


def writeParticipantTables(root_path, participant_rows, session_rows, scan_rows):
    """Write participants.tsv/.json and every _sessions.tsv / _scans.tsv."""
    import json

    from ..lib import tabular

    if participant_rows:
        # Merged, not overwritten: converting a second study into an existing dataset
        # must add to this table. Replacing it leaves the earlier subject's directory
        # with no row, which is a PARTICIPANT_ID_MISMATCH error.
        tabular.merge_participants(os.path.join(root_path, 'participants.tsv'),
                                   participant_rows)
        # Written with the table, never before it: the sidecar of a table that was
        # never created is an error, and every column here needs describing anyway
        # because `weight` is not a BIDS-defined column.
        descriptions = {'participant_id': {'Description': 'Participant identifier'}}
        descriptions.update(tabular.PARTICIPANT_DESCRIPTIONS)
        with open(os.path.join(root_path, 'participants.json'), 'w') as f:
            json.dump(descriptions, f, indent=4)
    for subject, rows in session_rows.items():
        tabular.write_tsv(os.path.join(root_path, subject, f'{subject}_sessions.tsv'),
                          ('session_id', 'acq_time'), rows)
    for (subject, session), rows in scan_rows.items():
        stem = f'{subject}_{session}' if session else subject
        directory = os.path.join(root_path, subject, session) if session \
            else os.path.join(root_path, subject)
        tabular.write_tsv(os.path.join(directory, f'{stem}_scans.tsv'),
                          ('filename', 'acq_time'), rows)


def completeFieldsCreateFolders (df, filtered_dset, dset, multi_session, root_path, subj_code):
    """Resolve BIDS path, directory and suffix for each scan and create the folders.

    Filenames, entity ordering and suffix validity are delegated to the BIDS schema
    via ``brkraw.lib.bids`` rather than assembled by hand here.  ``FileName`` holds the
    entity prefix (everything up to but excluding ``run``/``echo`` and the suffix); the
    converter appends those downstream so they land in spec-correct positions.

    Args:
        df (dataframe): original pandas dataframe (used for friendly datasheet errors)
        filtered_dset (dataframe): filtered pandas dataframe for one raw dataset
        dset (object): BrukerLoader(dpath) object
        multi_session (bool): whether the dataset uses sessions
        root_path (str): the root path of output folder
        subj_code (str): subject folder name, e.g. ``sub-001``
    Returns:
        dataframe: the completed filtered_dset.
    """
    import numpy as np
    import pandas as pd

    from ..lib import bids
    from ..lib.utils import bids_validation

    subj_id = subj_code.replace('sub-', '', 1)
    # modality may be assigned suffix strings below; ensure it can hold them.
    filtered_dset['modality'] = filtered_dset['modality'].astype(object)

    for i, row in filtered_dset.iterrows():
        # Resolve the BIDS suffix (datasheet 'modality'); auto-infer when blank.
        if pd.isnull(row.modality):
            method = scanMethod(dset, row.ScanID) or ''
            suffix = bids.default_suffix(row.DataType, method)
            if suffix is None:
                # Unknown method: cannot emit a valid BIDS suffix. Leave modality
                # blank; the converter routes these scans out of the validated tree.
                filtered_dset.loc[i, 'modality'] = np.nan
                continue
            filtered_dset.loc[i, 'modality'] = suffix
        else:
            bids_validation(df, i, 'modality', row.modality, 30, dtype=str)
            suffix = row.modality
        bids.validate_suffix(row.DataType, suffix)

        # Collect entity labels from the datasheet (run/echo handled downstream).
        entities = {'subject': subj_id}
        if multi_session:
            entities['session'] = row.SessID
        for col, ent in (('task', 'task'), ('acq', 'acquisition'), ('ce', 'ceagent'),
                         ('rec', 'reconstruction'), ('dir', 'direction')):
            val = getattr(row, col)
            if pd.notnull(val):
                bids_validation(df, i, col, val, 64)
                entities[ent] = val

        rel_dir, prefix = bids.build_prefix(entities, row.DataType)
        dtype_path = os.path.join(root_path, *rel_dir.split('/'))
        mkdir(dtype_path)
        filtered_dset.loc[i, 'FileName'] = prefix
        filtered_dset.loc[i, 'Dir'] = dtype_path

    return filtered_dset


def is_localizer(dset, scan_id, reco_id):
    ac_proc = get_value(dset.get_visu_pars(scan_id, reco_id), 'VisuAcquisitionProtocol')
    if ac_proc is None:
        return False
    ac_proc = str(ac_proc)
    return bool(re.search('tripilot', ac_proc, re.IGNORECASE)
                or re.search('localizer', ac_proc, re.IGNORECASE))


def override_header(pvobj, subjtype, position):
    """override subject position and subject type"""
    if position is not None:
        try:
            pvobj.override_position(position)
        except Exception:
            msg = f"Unknown position string [{position}]. Please check your input option." + \
                  "The position variable can be defiend as <BodyPart>_<Side>," + \
                  "available BodyParts are (Head, Foot, Tail) and sides are (Supine, Prone, Left, Right). (e.g. Head_Supine)"
            raise InvalidApproach(msg)
    if subjtype is not None:
        try:
            pvobj.override_subjtype(subjtype)
        except Exception:
            msg = f"Unknown subject type [{subjtype}]. Please check your input option." + \
                  "available options are (Biped, Quadruped, Phantom, Other, OtherAnimal)"
            raise InvalidApproach(msg)
    return pvobj


if __name__ == '__main__':
    main()
