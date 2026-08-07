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
    'NumberReceiveCoilActiveElements': 'PVM_EncNReceivers',  # BIDS type: integer
    # BIDS type: string (DICOM 0018,9049). Emit the transmit coil name only; a
    # nested object is a schema type error.
    'MRTransmitCoilSequence': 'VisuCoilTransmitName',
    # NOT a BIDS field -- see NON_SCHEMA_KEYS below.
    'CoilConfigName': 'ACQ_coil_config_file',
    # RecoCombineMode lives in pdata/N/reco, reachable since `reco` became a
    # parameter source. Its enum is verbatim BIDS-usable free text:
    # SumOfSquares / ShuffleImages / AddImages.
    'CoilCombinationMethod': 'RecoCombineMode',
    # SEQUENCE_SPECIFIC
    'PulseSequenceType': 'PULPROG',  # 'VisuAcqEchoSequenceType'
    'ScanningSequence': 'VisuAcqSequenceName',
    'SequenceVariant': 'VisuAcqEchoSequenceType',
    # BIDS: '2D' or '3D'. PVM_SpatDimEnum is '2D'/'3D' on PV6+; fall back to
    # VisuCoreDim (2/3) -> '2D'/'3D' for PV5.1.
    'MRAcquisitionType': ['PVM_SpatDimEnum', {'Dim': 'VisuCoreDim', 'Equation': "str(int(Dim)) + 'D'"}],
    'SequenceName': ['VisuAcquisitionProtocol', 'ACQ_protocol_name'],  # if first component are None
    'PulseSequenceDetails': 'ACQ_scan_name',
    # IN_PLANE_SPATIAL_ENCODING
    # True shot count of a (segmented) EPI; VisuAcqKSpaceTrajectoryCnt was the
    # trajectory count and returned 1 for every scan.
    'NumberShots': ['NSegments', 'PVM_EpiNShots'],
    # PPI (parallel-imaging) acceleration; ACQ_phase_factor was the RARE/EPI
    # echo-train (segmentation) factor -- not the acceleration.
    'ParallelReductionFactorInPlane': ['PVM_EncPpiAccel1', {'key': 'PVM_EncPpi', 'idx': 1}],
    # PVM_EncPpi is per logical axis: 2 elements in 2D (read, phase), 3 in 3D
    # (read, phase, slice), verified across 1413 corpus method files. The
    # out-of-plane factor therefore exists only for 3D.
    'ParallelReductionFactorOutOfPlane': {
        'P': 'PVM_EncPpi',
        'Equation': 'float(np.atleast_1d(P)[2]) if np.size(P) > 2 else None',
    },
    # Bruker's only parallel-imaging implementation is GRAPPA (k-space, auto-
    # calibrated -- PVM_EpiGrappaThresh/Coefficients). There is no image-domain
    # PPI, so this is never SENSE. Emitted only where the scan is accelerated.
    'ParallelAcquisitionTechnique': {
        'P': 'PVM_EncPpi',
        'Equation': "'GRAPPA' if np.max(np.atleast_1d(P)) > 1 else None",
    },
    # PV7/PV360 only; absent from the PV5.1 and PV6 headers entirely.
    'MultibandAccelerationFactor': 'PVM_MbEncAccelFactor',
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
    # Resolves the phase-encode AXIS (i/j/k) only, and is therefore NOT emitted as
    # BIDS `PhaseEncodingDirection`. That field has no unsigned value: the schema
    # says "the polarity is assumed to go from zero index to maximum index unless
    # `-` is present", so writing a bare 'j' asserts POSITIVE polarity rather than
    # abstaining -- which is what this code did for years while its comment claimed
    # otherwise.
    #
    # The sign is the product of three terms: the axis (derivable here), the k-space
    # traversal direction (derivable from PVM_EncSteps1), and the mapping from sorted
    # k-space row to image index that ParaVision's own reconstruction establishes.
    # That third term is written nowhere, so the sign is a coin flip per ParaVision
    # generation -- and a WRONG sign makes distortion correction worse than none.
    #
    # So the axis ships under a deliberately non-BIDS key (see NON_SCHEMA_KEYS),
    # which is also what dcm2niix emits when it cannot determine polarity. Set the
    # signed field yourself, from a reversed-PE acquisition, before using it for
    # TOPUP/SDC.
    'PhaseEncodingAxis': [
        {'key': 'VisuAcqGradEncoding', 'where': 'phase_enc'},
        'VisuAcqImagePhaseEncDir',
    ],
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
    #
    # BIDS wants ONE number. Variable-TR sequences (RAREVTR) return an array, e.g.
    # [5.5, 3.0, 1.5, 0.8, 0.4, 0.2] -- the same trap InversionTime already guards
    # against. Emitting the array is invalid, and the reference validator does not
    # catch it: RepetitionTime is named only in the func/bold and mrs rule groups,
    # so on an anat file no rule applies and the value is never type-checked.
    'RepetitionTime': {'TR': 'VisuAcqRepetitionTime',
                       'Equation': 'TR/1000 if np.ndim(TR) == 0 else None'},
    # Wall-clock duration of the acquisition, in seconds. PVM_ScanTime does not
    # exist on PV5.1 (only the display string PVM_ScanTimeStr), so the previous
    # mapping silently emitted nothing there; VisuAcqScanTime is written by every
    # ParaVision version and is identical where both exist. Deprecated by BIDS for
    # func -- dropped in the func merge, see lib/utils.get_bids_ref_obj.
    'AcquisitionDuration': {'T': 'VisuAcqScanTime', 'Equation': 'T/1000'},
    # Time between successive excitations. For most methods that is the sequence
    # TR, but MDEFT prepares a whole segment per inversion: there PVM_RepetitionTime
    # IS SegmRepTime (verified equal on PV5.1, PV6 and PV7 MDEFT scans) and the
    # excitation TR is EchoRepTime, so that is tried first.
    'RepetitionTimeExcitation': [
        {'T': 'EchoRepTime', 'Equation': 'T/1000'},
        {'T': 'PVM_RepetitionTime', 'Equation': 'T/1000 if np.ndim(T) == 0 else None'},
    ],
    # Time from one preparation (inversion) pulse to the next -- the segment TR of
    # a magnetization-prepared sequence. Only such methods declare it.
    'RepetitionTimePreparation': {'T': 'SegmRepTime', 'Equation': 'T/1000'},
    # Inter-volume delay of a (segmented) EPI, in seconds. ParaVision floors this
    # parameter at 0.001 ms, so that value means "no delay" rather than 1 ns.
    'DelayTime': {'D': 'PackDel', 'Equation': 'D/1000.0 if D > 0.001 else None'},
    # Only meaningful when the trigger module is actually enabled; PVM_TriggerDelay
    # keeps its last value otherwise (1 ms throughout the corpus, with the module Off).
    'DelayAfterTrigger': {'M': 'PVM_TriggerModule', 'D': 'PVM_TriggerDelay',
                          'Equation': "D/1000.0 if M == 'On' else None"},
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
    # MAGNETIZATION TRANSFER
    # Whether an MT module was played. PV360 renames the parameter. The MT *pulse*
    # parameters are present even when the module is off, so they describe a pulse
    # that was never played -- they stay unmapped, see UNMAPPED_WITH_SOURCE.
    'MTState': [
        {'MT': 'PVM_MagTransOnOff', 'Equation': "MT == 'On'"},
        {'MT': 'PVM_SatTransOnOff', 'Equation': "MT == 'On'"},
    ],
    # SPOILING
    # VisuAcqSpoiling (PV6+) states the spoiling regime directly and its enum maps
    # one-to-one onto the BIDS one. NotSpoiled yields SpoilingState False and no
    # SpoilingType, which is what BIDS wants -- an unspoiled sequence has no type.
    'SpoilingState': {'S': 'VisuAcqSpoiling', 'Equation': "S != 'NotSpoiled'"},
    'SpoilingType': {
        'S': 'VisuAcqSpoiling',
        'Equation': "{'RFSpoiled': 'RF', 'GradientSpoiled': 'GRADIENT', "
                    "'RFAndGradientSpoiled': 'COMBINED'}.get(S)",
    },
    # Bruker's RF-spoiling phase list is generated with a fixed 117 degree
    # increment -- MRT_RFSpoilPhaseList(117, ...) in
    # resources/PV6.0.1/prog/parx/src/FLASH/backbone.c:660. The value is not stored
    # in any parameter, so it is emitted only where the sequence declares RF
    # spoiling on (a FLASH-family parameter; PV5.1 spells it RFSpoilerOnOff).
    'SpoilingRFPhaseIncrement': [
        {'R': 'RFSpoiling', 'Equation': "117.0 if R == 'Yes' else None"},
        {'R': 'RFSpoilerOnOff', 'Equation': "117.0 if R == 'On' else None"},
    ],
    # WATER SUPPRESSION
    # The flag and the mode disagree in real data -- On/NO_SUPPRESSION appears 14
    # times and Off/VAPOR twice across the corpus -- so neither alone is a safe
    # answer. Water is suppressed only when the module is on AND a technique is set.
    'WaterSuppression': {'ON': 'PVM_WsOnOff', 'MODE': 'PVM_WsMode',
                         'Equation': "ON == 'On' and MODE != 'NO_SUPPRESSION'"},
    'WaterSuppressionTechnique': {
        'ON': 'PVM_WsOnOff', 'MODE': 'PVM_WsMode',
        'Equation': "MODE if (ON == 'On' and MODE != 'NO_SUPPRESSION') else None",
    },
    # SHIMMING
    # BIDS wants free text. PVM_ReqShimEnum is the technique itself: Current_Shim
    # (reuse the standing shim) or Map_Shim (shim computed from a field map).
    'B0ShimmingTechnique': 'PVM_ReqShimEnum',
    # INSTITUTION_INFORMATION
    'InstitutionName': 'VisuInstitution',
}


FMRI_META_REF = {  # RepetitionTime now lives in COMMON_META_REF (emitted for every scan);
    # keeping it out of here avoids a duplicate-key clash when the two-step
    # template merges 'common' and 'func' (see utils.get_bids_ref_obj).
    'VolumeTiming': {
        'TR': 'VisuAcqRepetitionTime',
        'NR': 'PVM_NRepetitions',
        'Equation': '(np.arange(NR)*(TR/1000)).tolist()',
    },
    # Dummy/steady-state scans discarded by the scanner. PVM_DummyScans does not
    # exist on PV5.1 (the EPI method declares NDummyScans locally), and it counts
    # TR PERIODS rather than volumes -- PVM_DummyScansDur = PVM_DummyScans *
    # PVM_RepetitionTime, so a single-slice scan can report 226. The two coincide
    # only where one TR is one volume, i.e. EPI, which is exactly where this key is
    # merged (bold/cbv/epi), so the value is meaningful here and nowhere else.
    'NumberOfVolumesDiscardedByScanner': ['PVM_DummyScans', 'NDummyScans'],
}


#: Merged for fieldmap modalities. `IntendedFor` is deliberately absent: it names
#: the images a fieldmap corrects, which no Bruker parameter records. It is set by
#: the converter instead (save_json's `intended_for` argument). It used to sit here
#: as `''`, which survived the None-strip and wrote an empty string into every
#: fieldmap sidecar.
FIELDMAP_META_REF = {
    # The two echo times a phase-difference fieldmap was built from, in seconds.
    # EffectiveTE (ms) holds them in order. Deliberately NOT PVM_EchoTime, which is
    # the echo *spacing* in FieldMap/RARE/MSME and only the first TE in MGE/FLASH --
    # the same name meaning two different things. Lives here rather than in
    # COMMON_META_REF so it reaches fieldmap sidecars only: on a multi-echo anat the
    # first two echoes of a train are not what these fields mean.
    'EchoTime1': {'TE': 'EffectiveTE',
                  'Equation': 'float(np.atleast_1d(TE)[0])/1000.0 if np.size(TE) > 1 else None'},
    'EchoTime2': {'TE': 'EffectiveTE',
                  'Equation': 'float(np.atleast_1d(TE)[1])/1000.0 if np.size(TE) > 1 else None'},
}

#: BIDS fields this converter fills in code rather than from a mapping table,
#: because they need something the resolver above cannot see -- the datasheet, the
#: written NIfTI, or the caller's intent. Value is where it happens.
COMPUTED_AT_WRITE = {
    'TaskName': 'save_json(task_name=...), from the datasheet task- entity',
    'IntendedFor': 'save_json(intended_for=...); no Bruker parameter records intent',
    'Units': "save_json's fieldmap branch, via _bids_fieldmap_units(VisuCoreDataUnits)",
}

#: Fields with a real Bruker source that is deliberately still not wired up, and why.
#: Every remaining entry is here because the mapping cannot be *verified* against the
#: corpus -- either the parameter never takes a meaningful value in it, or the
#: conversion to the BIDS field is a guess. Emitting an unverified value is worse than
#: emitting nothing: it is wrong data wearing the right key. Each entry says what
#: would settle it.
UNMAPPED_WITH_SOURCE = {
    # PVM_MagTransOnOff is 'Off' in all 1642 corpus method files that declare it, so
    # the pulse parameters below always describe a module that was never played, and
    # the struct indexing cannot be checked against a scan that used it. They are read
    # from PVM_MagTransPulse1, which is a struct ROW (a list of lists), not the flat
    # array the field order suggests -- exactly the kind of detail that needs a real
    # MT-on scan to confirm. Needs: one acquisition with MT enabled.
    'MTOffsetFrequency': 'PVM_MagTransOffset (Hz); no corpus scan has MT on',
    'MTPulseBandwidth': 'PVM_MagTransPulse1[0][1] (.Bandwidth, Hz); no corpus scan has MT on',
    'MTNumberOfPulses': 'PVM_MagTransPulsNumb; no corpus scan has MT on',
    'MTPulseDuration': 'PVM_MagTransPulse1[0][0] (.Length, ms -> s); no corpus scan has MT on',
    'MTPulseShape': 'PVM_MagTransPulse1Enum; no corpus scan has MT on, and only bp/gauss/'
                    'sinc reach a BIDS enum value -- FERMI/GAUSSHANN/SINCHANN/SINCGAUSS '
                    'have no Bruker equivalent',
    # Bruker has three independent spoilers (ReadSpoiler, SliceSpoiler,
    # RepetitionSpoiler) with different durations on the same scan -- e.g. 0.900 ms
    # and 0.225 ms on PV6 lego scan 3. BIDS has one field, so choosing among them is
    # a guess. Needs: a decision on which lobe the BIDS field means.
    'SpoilingGradientDuration': 'ReadSpoiler/SliceSpoiler/RepetitionSpoiler .dur (ms -> s); '
                                'they differ on the same scan and BIDS has only one field',
    'SpoilingGradientMoment': 'derivable as (ampl/100) * Gmax * dur with Gmax from '
                              'PVM_GradCalConst, but nothing records the moment itself, so '
                              'the derivation cannot be checked against ground truth',
    'ScanOptions': 'PV6+ composition of VisuAcqSaturation / VisuAcqPartialFourier / '
                   'VisuAcqSpectralSuppression / VisuAcqFlowCompensation / '
                   'VisuCardiacSynchUsed / VisuRespSynchUsed into DICOM (0018,0022) codes. '
                   'ParaVision itself leaves that DICOM tag empty on PV5.1/PV6, so the '
                   'code composition would be ours to invent',
    'B1ShimmingTechnique': 'PVM_TxCoilScMode1 is AutoAdj in all 342 corpus files -- a '
                           'transmit-coil scaling adjustment, not B1 shimming, which needs '
                           'a pTx system the corpus has no example of',
    'ContrastBolusIngredient': 'VisuContrastIngredients -- PV360 only, and absent from every '
                               'file in the corpus, so the enum transform (strip '
                               '_INGREDIENT, _ -> space) cannot be checked',
}

#: Fields with no Bruker source, and why. Searched across the PV5.1 and PV6.0.1
#: installs, the manuals, and the corpus. Recording the reason is the point: it is
#: what stops the next person repeating the search, and several of these entries
#: replace comments that asserted "no source" wrongly.
NO_BRUKER_SOURCE = {
    'PhaseEncodingDirection': 'no source for the field as BIDS defines it. The AXIS is '
                              'derivable (VisuAcqGradEncoding) and so is the k-space '
                              'traversal direction (PVM_EncSteps1), but the third term -- '
                              "the map from sorted k-space row to image index that "
                              "ParaVision's reconstruction fixes -- is written nowhere. "
                              'BIDS has no unsigned value, so the axis alone ships as '
                              'PhaseEncodingAxis (see NON_SCHEMA_KEYS) rather than as a '
                              'polarity claim we cannot support',
    'ReceiveCoilActiveElements': 'VisuCoilReceiveType is the coil geometry KIND '
                                 '(VOLUME_COIL/SURFACE_COIL), not the active element set',
    'NumberTransmitCoilActiveElements': 'no parameter enumerates transmit elements',
    'GradientSetType': 'CONFIG_SCAN_gradient_system in the `configscan` file does carry it '
                       "(e.g. 'B-GA12SHP FOR BC70/20 TYP 2'), but brukerapi does not load "
                       'that file and reading it here would undo ADR 0002. Upstream issue '
                       'filed; revisit when brukerapi exposes it',
    'MatrixCoilMode': 'no DICOM 0018,9008 equivalent. PVM_EncNReceivers/PVM_EncActReceivers '
                      'describe receiver count, not the analog combination mode',
    'NonlinearGradientCorrection': 'PV5.1/PV6 perform no gradient-nonlinearity unwarping; '
                                   'zero hits for nonlinear/gradwarp/unwarp in either install',
    'AnatomicalLandmarkCoordinates': 'zero hits for "landmark" in either install; no AC/PC '
                                     'or named-fiducial parameter exists',
    'InstitutionAddress': 'VisuInstitution is the only institution parameter; DICOM '
                          '(0008,0081) is absent from the conformance statement',
    'InstitutionalDepartmentName': 'DICOM (0008,1040) absent from the conformance statement',
    'B0FieldIdentifier': 'a BIDS organisational label, not a measurement; synthesised by '
                         'the converter when fieldmap pairing lands',
    'B0FieldSource': 'as B0FieldIdentifier',
    'TablePosition': 'ACQ_position_X/Y/Z are hard-assigned 0 in every method; no table '
                     'position is recorded',
    'FrameAcquisitionDuration': 'VisuAcqFrameTime is declared in PV6 but written to zero '
                                'real visu_pars files across PV5/6/7/360',
    'NumberOfVolumesDiscardedByUser': 'post-hoc by definition; nothing on the scanner knows',
    'NegativeContrast': 'no parameter',
    'MixingTime': 'StTM exists but is STEAM single-voxel MRS; BIDS requires MixingTime for '
                  'the TB1EPI suffix, which Bruker has no equivalent of',
    'MultipartID': 'a curator-chosen grouping key',
    'BodyPart': 'zero hits; DICOM (0018,0015) is not exported',
    'BodyPartDetails': 'as BodyPart',
    'BodyPartDetailsOntology': 'as BodyPart',
    'DeidentificationMethod': 'PV360 has only the boolean VisuInstanceDeIdentified, not the '
                              'array of objects BIDS defines',
    'DeidentificationMethodCodeSequence': 'as DeidentificationMethod',
    'Resolution': 'a derivatives entity descriptor, not an acquisition property',
    'Density': 'as Resolution',
    'SampleStaining': 'microscopy only',
    'SamplePrimaryAntibody': 'microscopy only',
    'SampleSecondaryAntibody': 'microscopy only',
    'HardcopyDeviceSoftwareVersion': 'deprecated by BIDS; never emit',
    'Instructions': 'user-supplied; describes the session, not the scan',
    'TaskDescription': 'user-supplied',
    'CogAtlasID': 'user-supplied',
    'CogPOID': 'user-supplied',
}

#: Keys we emit that BIDS does not define. Legal -- a sidecar may carry extra keys --
#: but recorded here so they are distinguishable from a typo'd real field, and so the
#: guard test below can tell "deliberate" from "unaccounted for".
NON_SCHEMA_KEYS = {
    'CoilConfigName': 'ACQ_coil_config_file; useful provenance with no BIDS equivalent',
    'PhaseEncodingAxis': 'the PE axis without a polarity claim. BIDS '
                         'PhaseEncodingDirection has no unsigned value, so a bare "j" '
                         'would assert positive polarity we cannot prove. Same key '
                         'dcm2niix emits when it cannot determine the sign',
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
