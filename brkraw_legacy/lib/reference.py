SLICE_ORIENT = {
    0: {1: 'L->R', 3: 'R->L'},
    1: {1: 'P->A', 3: 'A->P'},
    2: {1: 'F->H', 3: 'F->H'},
}

ISSUE_REPORT = (
    'Please report the issue at (https://github.com/dvm-shlee/bruker/issues) with the error message.'
)

ERROR_MESSAGES = {
    'ImportError': '[{}] is not recognized as ParavisionDataset.',
    'NoSlicePacksDef': 'NoneType VisuCoreSlicePacksDef.',
    'SliceDistDatatype': 'unexpected datatype of VisuCoreSliceDist.',
    'SlicePacksSlices': 'unexpected datatype of VisuCoreSlicePacksSlices',
    'DimType': 'non compatible dimension type.',
    'NumOrientMatrix': 'unexpected number of element in VisuCoreOrientation.',
    'NumSlicePosition': 'unexpected number of element in VisuCorePosition.',
    'PhaseEncDir': 'unexpected phase encoding direction.',
    'NotIntegrated': 'not integrated method, please contact developer.',
}

# BIDS v1.10.0
# Below is the list of METADATA keywords that BIDS recommended
COMMON_METADATA_FIELD = {
    'Recommended': [  # SCANNER_HARDWARE
        'Manufacturer',
        'ManufacturersModelName',
        'DeviceSerialNumber',
        'StationName',
        'SoftwareVersions',
        'MagneticFieldStrength',
        'ReceiveCoilName',
        'ReceiveCoilActiveElements',
        'NumberReceiveCoilActiveElements',
        'GradientSetType',
        'MRTransmitCoilSequence',
        'MatrixCoilMode',
        'CoilCombinationMethod',
        # SEQUENCE_SPECIFIC
        'MRAcquisitionType',
        'PulseSequenceType',
        'ScanningSequence',
        'SequenceVariant',
        'ScanOptions',
        'SequenceName',
        'PulseSequenceDetails',
        'NonlinearGradientCorrection',
        # IN_PLANE_SPATIAL_ENCODING
        'NumberShots',
        'ParallelReductionFactorInPlane',
        'ParallelAcquisitionTechnique',
        'PartialFourier',
        'PartialFourierDirection',
        'PhaseEncodingDirection',
        'EffectiveEchoSpacing',
        'TotalReadoutTime',
        # TIMING_PARAMETERS
        'EchoTime',
        'InversionTime',
        'SliceTiming',
        'SliceEncodingDirection',
        'DwellTime',
        # RF_AND_CONTRAST, SLICE_ACCELERATION
        'FlipAngle',
        'MultibandAccelerationFactor',
        'AnatomicalLandmarkCoordinates',
        # INSTITUTION_INFORMATION
        'InstitutionName',
        'InstitutionAddress',
        'InstitutionalDepartmentName',
    ],
    'Optional': [  # RF_AND_CONTRAST
        'NegativeContrast',
        # ACQUISITION_SPECIFIC
        'ContrastBolusIngredient',
    ],
    'Deprecated': [  # SCANNER_HARDWARE
        'HardcopyDeviceSoftwareVersion'
    ],
}

# Matadata Field Mapping for Bruker PvDataset
# BIDS Meta data will be automatically created according to below reference.
# If list is entered as value, each parameter will be tested and the first available value will be returned.
# If dict is entered as value, below condition will be tested.
#   If key - where pair:  parse value from given key and return index of 'where' from these values
#   If key - idx pair:    parse value from given key and return value of given 'idx'
#   If 'Equation' in key: each key assigned as local variable and test in Equation will be executed to return the value
#   Else, new key - value dictionary will be return (for the cases with sub-keys)
# If string is entered as value, The value of given parameter will be parsed from parameter files
COMMON_META_REF = {
    'Manufacturer': 'VisuManufacturer',
    'ManufacturersModelName': 'VisuStation',
    'DeviceSerialNumber': {'SN': 'VisuSystemOrderNumber', 'Equation': 'str(SN)'},  # BIDS type: string
    'StationName': 'VisuStation',
    # BIDS RECOMMENDED scanner field is plural 'SoftwareVersions' (DICOM
    # 0018,1020); the singular 'SoftwareVersion' is the stimulus-presentation
    # field. ACQ_sw_version is the PV5.1 fallback.
    'SoftwareVersions': ['VisuAcqSoftwareVersion', 'ACQ_sw_version'],
    'MagneticFieldStrength': {'Freq': 'VisuAcqImagingFrequency', 'Equation': 'Freq / 42.576'},
    'ReceiveCoilName': 'VisuCoilReceiveName',
    # VisuCoilReceiveType is the coil geometry KIND (VOLUME_COIL/SURFACE_COIL/
    # ...), not the set of active receive elements the BIDS field asks for.
    'ReceiveCoilActiveElements': None,
    'NumberReceiveCoilActiveElements': 'PVM_EncNReceivers',  # BIDS type: integer
    # ACQ_status is an acquisition-status code (e.g. 'S116'), unrelated to the
    # gradient coil/set; no Bruker parameter encodes a gradient set type.
    'GradientSetType': None,
    # BIDS type: string (DICOM 0018,9049). Emit the transmit coil name only; a
    # nested object is a schema type error.
    'MRTransmitCoilSequence': 'VisuCoilTransmitName',
    'CoilConfigName': 'ACQ_coil_config_file',  # if Transmit and Receive coil info in None
    # ACQ_experiment_mode is single-vs-parallel/multiple-receiver EXPERIMENT
    # mode, not the analog array-coil combination mode BIDS means.
    'MatrixCoilMode': None,
    'CoilCombinationMethod': None,
    # SEQUENCE_SPECIFIC
    'PulseSequenceType': 'PULPROG',  # 'VisuAcqEchoSequenceType'
    'ScanningSequence': 'VisuAcqSequenceName',
    'SequenceVariant': 'VisuAcqEchoSequenceType',
    # BIDS: '2D' or '3D'. PVM_SpatDimEnum is '2D'/'3D' on PV6+; fall back to
    # VisuCoreDim (2/3) -> '2D'/'3D' for PV5.1.
    'MRAcquisitionType': ['PVM_SpatDimEnum', {'Dim': 'VisuCoreDim', 'Equation': "str(int(Dim)) + 'D'"}],
    # BIDS ScanOptions is an array of DICOM scan-option codes; the Bruker
    # flags below do not map cleanly to that type, so it is left unset.
    'ScanOptions': None,
    'SequenceName': ['VisuAcquisitionProtocol', 'ACQ_protocol_name'],  # if first component are None
    'PulseSequenceDetails': 'ACQ_scan_name',
    # BIDS type: boolean. Bruker VisuAcqKSpaceTraversal is a string, not a
    # gradient-nonlinearity-correction flag, so it is left unset.
    'NonlinearGradientCorrection': None,
    # IN_PLANE_SPATIAL_ENCODING
    # True shot count of a (segmented) EPI; VisuAcqKSpaceTrajectoryCnt was the
    # trajectory count and returned 1 for every scan.
    'NumberShots': ['NSegments', 'PVM_EpiNShots'],
    # PPI (parallel-imaging) acceleration; ACQ_phase_factor was the RARE/EPI
    # echo-train (segmentation) factor -- not the acceleration.
    'ParallelReductionFactorInPlane': ['PVM_EncPpiAccel1', {'key': 'PVM_EncPpi', 'idx': 1}],
    'ParallelAcquisitionTechnique': None,
    # Phase-axis partial-Fourier fraction = 1/accel: Bruker PVM_EncPft[1] /
    # PVM_EncPftAccel1 is an acceleration factor (>= 1), emitted only when the
    # phase axis is actually under-sampled (accel > 1).
    'PartialFourier': [
        {'PFT': 'PVM_EncPftAccel1', 'Equation': '1.0/PFT if PFT>1 else None'},
        {'PFT': {'key': 'PVM_EncPft', 'idx': 1}, 'Equation': '1.0/PFT if PFT>1 else None'},
    ],
    'PartialFourierDirection': [
        {'PFT': 'PVM_EncPftAccel1', 'Equation': '"phase" if PFT>1 else None'},
        {'PFT': {'key': 'PVM_EncPft', 'idx': 1}, 'Equation': '"phase" if PFT>1 else None'},
    ],
    # Resolves only the phase-encode AXIS (i/j/k), not the polarity sign
    # (i-/j-/k-). The sign depends on the PE gradient polarity, k-space
    # traversal, and reconstruction flips relative to the written voxel
    # frame; it cannot be derived reliably from these parameters alone, and a
    # WRONG sign makes susceptibility distortion correction worse. It is left
    # unsigned -- validate/set it per acquisition (e.g. with a reversed-PE
    # fieldmap) before using it for TOPUP/SDC.
    'PhaseEncodingDirection': [
        {'key': 'VisuAcqGradEncoding', 'where': 'phase_enc'},
        'VisuAcqImagePhaseEncDir',
    ],  # Deprecated
    # EPI echo spacing (seconds), reduced by the in-plane parallel factor.
    # PVM_EpiEchoSpacing (ms) is Bruker's console echo spacing; it is absent
    # for non-EPI sequences, so this field is emitted only where it applies
    # (the old 1/(EncMatrix*PixelBandwidth) basis returned the ADC sample dwell,
    # ~readout-matrix times too small, on every sequence).
    'EffectiveEchoSpacing': {
        'ES': 'PVM_EpiEchoSpacing',
        'ACC': ['PVM_EncPpiAccel1', {'key': 'PVM_EncPpi', 'idx': 1}, 1],
        'Equation': '(ES/1000.0)/ACC',
    },
    # FSL/BIDS TotalReadoutTime = EffectiveEchoSpacing * (ReconMatrixPE - 1),
    # ReconMatrixPE = PVM_Matrix on the phase axis. EPI only (PVM_EpiEchoSpacing).
    'TotalReadoutTime': {
        'ES': 'PVM_EpiEchoSpacing',
        'ACC': ['PVM_EncPpiAccel1', {'key': 'PVM_EncPpi', 'idx': 1}, 1],
        'NPE': {'key': 'PVM_Matrix', 'idx': [{'key': 'VisuAcqGradEncoding', 'where': 'phase_enc'}, 1]},
        'Equation': '((ES/1000.0)/ACC)*(NPE-1)',
    },
    # TIMING_PARAMETERS
    'EchoTime': {'TE': 'VisuAcqEchoTime', 'Equation': 'np.array(TE)/1000'},
    # BIDS wants a single number in SECONDS. Bruker VisuAcqInversionTime is in
    # ms, and is an array for multi-TI (e.g. Look-Locker) sequences -> convert
    # the scalar case to seconds; leave multi-TI unset (not a single number).
    'InversionTime': {'TI': 'VisuAcqInversionTime', 'Equation': 'TI/1000 if np.ndim(TI) == 0 else None'},
    # RepetitionTime is REQUIRED for func and valid for anat/dwi, so emit it
    # for every scan. It used to live only in FMRI_META_REF, so the one-shot
    # conversion path (save_json with metadata=None) produced func sidecars
    # missing this required field.
    'RepetitionTime': {'TR': 'VisuAcqRepetitionTime', 'Equation': 'TR/1000'},
    # One acquisition time per reconstructed slice (seconds). ACQ_obj_order is
    # the slice acquisition order; argsort inverts it to each slice's time.
    # Emit only when the order length equals the multi-slice count (NSLICES);
    # multi-echo/multi-TI orders have length NSLICES*N and are skipped.
    # save_json additionally drops it if the length ever disagrees with the
    # written NIfTI's slice dimension.
    'SliceTiming': {
        'TR': 'VisuAcqRepetitionTime',
        'Order': 'ACQ_obj_order',
        'NS': 'NSLICES',
        'Equation': '(np.argsort(np.asarray(Order)) * (TR/1000.0/NS)).tolist() '
        'if (NS is not None and NS > 1 and np.size(Order) == NS) else None',
    },
    # brkraw always reconstructs slices along the 3rd (k) axis; emit 'k' for
    # multi-slice data, else unset. (BIDS requires a string i/j/k, not the
    # integer the old where/len mapping produced.)
    'SliceEncodingDirection': {'NS': 'NSLICES', 'Equation': "'k' if (NS and NS > 1) else None"},
    # Receiver dwell time per readout point (seconds) = 1/bandwidth. PVM_EffSWh
    # (== SW_h) is the full sampling bandwidth in Hz; 1/VisuAcqPixelBandwidth
    # was the whole-line duration (too large by the readout matrix size).
    'DwellTime': {'SWh': ['PVM_EffSWh', 'SW_h'], 'Equation': '1/SWh'},
    # RF_AND_CONTRAST, SLICE_ACCELERATION
    # BIDS requires FlipAngle > 0; drop non-positive values.
    'FlipAngle': {'FA': 'VisuAcqFlipAngle', 'Equation': 'FA if np.all(np.asarray(FA) > 0) else None'},
    'MultibandAccelerationFactor': None,  # no Bruker SMS/multiband parameter on PV5/6/7
    'AnatomicalLandmarkCoordinates': None,
    # INSTITUTION_INFORMATION
    'InstitutionName': 'VisuInstitution',
    'InstitutionAddress': None,
    'InstitutionalDepartmentName': None,
}


FMRI_META_REF = {  # RepetitionTime now lives in COMMON_META_REF (emitted for every scan);
    # keeping it out of here avoids a duplicate-key clash when the two-step
    # template merges 'common' and 'func' (see utils.get_bids_ref_obj).
    'VolumeTiming': {
        'TR': 'VisuAcqRepetitionTime',
        'NR': 'PVM_NRepetitions',
        'Equation': '(np.arange(NR)*(TR/1000)).tolist()',
    },
    'TaskName': None,
    # RECOMMENDED
    # - timing parameters
    'NumberOfVolumesDiscardedByScanner': 'PVM_DummyScans',
    'NumberOfVolumesDiscardedByUser': None,
    'DelayTime': None,
    'AcquisitionDuration': {'TR': "PVM_ScanTime", 'Equation': "TR/1000"},
    'DelayAfterTrigger': None,
    # - fMRI task information
    'Instructions': None,
    'TaskDescription': None,
    'CogAtlasID': None,  # user-fillable; omitted when unset
    'CogPOID': None,  # user-fillable; omitted when unset
}


FIELDMAP_META_REF = {
    'IntendedFor': '',
}

DATASET_DESC_REF = {
    'Name': 'Untitled',
    # Filled from the loaded schema (lib.bids.BIDS_VERSION) at write time; the key is
    # kept here to hold its position in the emitted JSON. Left empty on purpose: an
    # unfilled value is stripped with the other placeholders, which is a safer failure
    # than shipping a version literal that has drifted from the schema we validate with.
    'BIDSVersion': '',
    'DatasetType': 'raw',
    'License': '',
    'Authors': [],
    'Acknowledgements': '',
    'HowToAcknowledge': '',
    'Funding': [],
    'EthicsApprovals': [],
    'ReferencesAndLinks': [],
    'DatasetDOI': '',
}

XYZT_UNITS = {'EPI': ('mm', 'sec')}
