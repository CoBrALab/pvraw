"""ASL: which volume is control and which is label.

BIDS wants an ``aslcontext.tsv`` with one row per volume saying what that volume
is. Bruker does not store that list; it stores a frame-group layout, and the
answer has to be reconstructed from it.

Nothing about the layout is fixed. Across the corpus the same information appears
as ``(MOVIE, IRMODE)``, ``(IRMODE, MOVIE)`` -- reversed by ``PVM_FairMode``
``INTERLEAVED2`` -- ``(SLICE, IRMODE, CYCLE)``, and for CASL ``(SLICE, MOVIE,
CYCLE)``. So the labelling axis is found by NAME and the volume order is derived
from the declared axes, never assumed.

The element labels vary too, which is why they are matched by prefix rather than
by equality:

    PV5.1        'Selective Inversion Mode' / 'Non-selective Inversion Mode'
    PV6, PV7     'Selective Inversion'      / 'Non-selective Inversion'
    PV7 (some)   'S TI: 1000.0 ms'          / 'NS TI: 1000.0 ms'

Note that 'Selective' is a prefix of nothing, but 'S' is a prefix of both -- so
non-selective must be tested first, or every label is read as a control.
"""
import numpy as np

from .errors import InvalidValueInField
from .utils import get_value

#: The slice axis is not a volume axis: the converter moves it to k, so it must be
#: excluded before working out how many volumes there are.
_SLICE_GROUP = 'FG_SLICE'

#: FAIR states the condition on its inversion-mode axis; CASL names each movie
#: frame directly.
_FAIR_AXIS = 'FG_IRMODE'
_CASL_COMMENT = 'CASL'

#: BIDS volume_type values used here. `deltam` and `cbf` are computed images that
#: ParaVision does not write, and `m0scan` is a separate acquisition.
CONTROL, LABEL = 'control', 'label'


def _elements(visu_pars):
    comments = get_value(visu_pars, 'VisuFGElemComment')
    return [] if comments is None else [str(c) for c in np.atleast_1d(comments)]


def _axes(visu_pars):
    """``[(name, size), ...]`` for the frame groups that make volumes."""
    desc = get_value(visu_pars, 'VisuFGOrderDesc')
    if desc is None:
        return []
    rows = desc if isinstance(desc[0], (list, tuple)) else [desc]
    return [(str(r[1]), int(r[0])) for r in rows if str(r[1]) != _SLICE_GROUP]


def _fair_condition(comment):
    """`control` or `label` for one FAIR inversion-mode label.

    Slice-selective inversion leaves inflowing arterial blood untouched, so it is
    the control; a non-selective inversion tags it. That is the definition of FAIR
    rather than a guess about this vendor -- but the *label* is still read from the
    file, and an unrecognised one raises instead of falling back to axis order.
    """
    text = comment.strip().lower()
    # Non-selective first: 's' prefixes both spellings of the short form.
    if text.startswith(('non-selective', 'nonselective', 'ns ', 'ns:')):
        return LABEL
    if text.startswith(('selective', 's ', 's:')):
        return CONTROL
    return None


def _casl_condition(comment):
    text = comment.strip().lower()
    if text.startswith('label'):
        return LABEL
    if text.startswith('control'):
        return CONTROL
    return None


def labelling_axis(visu_pars):
    """``(index into _axes, [volume_type per element])``, or None if not ASL.

    Found by axis name, not by matching element counts: a scan can easily have two
    axes of the same length (PV7 scan 16 is slice=2, irmode=2), and guessing
    between them would silently invert the perfusion signal.
    """
    axes = _axes(visu_pars)
    elements = _elements(visu_pars)
    if not axes or not elements:
        return None

    desc = get_value(visu_pars, 'VisuFGOrderDesc')
    rows = desc if isinstance(desc[0], (list, tuple)) else [desc]
    comments = {str(r[1]): (str(r[2]) if r[2] is not None else '') for r in rows}

    for position, (name, size) in enumerate(axes):
        if name == _FAIR_AXIS:
            resolver = _fair_condition
        elif name == 'FG_MOVIE' and _CASL_COMMENT in comments.get(name, ''):
            resolver = _casl_condition
        else:
            continue
        if len(elements) != size:
            raise InvalidValueInField(
                f'ASL labelling axis {name} declares {size} elements but '
                f'VisuFGElemComment lists {len(elements)}; refusing to guess.')
        types = [resolver(c) for c in elements]
        if any(t is None for t in types):
            raise InvalidValueInField(
                f'Unrecognised ASL element labels {elements!r}. Refusing to fall back '
                'to axis order -- PVM_FairMode INTERLEAVED2 reverses it, so a guess '
                'would invert control and label.')
        return position, types
    return None


def labeling_type(method):
    """``'PASL'`` or ``'CASL'`` from the method name, else None.

    No parameter states it. FAIR is a pulsed method and Bruker's CASL is continuous;
    no ParaVision version present ships a pCASL method at all, so ``PCASL`` is not
    reachable and is never guessed at.
    """
    name = str(method or '').upper()
    if 'FAIR' in name:
        return 'PASL'
    if 'CASL' in name:
        return 'CASL'
    return None


def _first_number(*candidates):
    """The first candidate that is a plain number.

    Not `a or b`: these parameters can be arrays -- VisuAcqRepetitionTime is one on
    a variable-TR scan -- and an array has no truth value, so `or` raises rather
    than falling through.
    """
    for value in candidates:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def sidecar_fields(method_name, method, visu_pars, types, n_slices=None):
    """The ASL sidecar fields that the mapping tables cannot express.

    They need the method name, the frame-group layout or the volume count, none of
    which a per-parameter mapping can see -- so they are computed here rather than
    split between two mechanisms.

    Several are constants because ParaVision has no module for the thing BIDS asks
    about: no FAIR or CASL method in any version present has background suppression,
    a Q2TIPS/QUIPSS bolus cut-off, or a flow crusher. Stating ``false`` is a fact
    about the sequence, not a placeholder.
    """
    kind = labeling_type(method_name)
    if kind is None or not types:
        return {}

    fields = {
        'ArterialSpinLabelingType': kind,
        'BackgroundSuppression': False,
        'VascularCrushing': False,
        # No Bruker parameter records an M0 acquisition, and none of these methods
        # writes one. A separate M0 scan has to be declared by the operator.
        'M0Type': 'Absent',
        # Pairs actually formed. CASL in Dynamic mode sets label and control counts
        # independently -- the corpus has one label against three controls -- so this
        # is the number of usable pairs rather than half the volume count.
        'TotalAcquiredPairs': min(types.count(LABEL), types.count(CONTROL)) or None,
    }
    if kind == 'PASL':
        # Bruker FAIR has no Q2TIPS/QUIPSS module, so no bolus cut-off was applied.
        # Saying so keeps BolusCutOffDelayTime/Technique from being required.
        fields['BolusCutOffFlag'] = False
        # Free text in BIDS. FAIR is the only pulsed scheme ParaVision ships.
        fields['PASLType'] = 'FAIR'
        thickness = _first_number(get_value(method, 'PVM_FairInvSlabThick'),
                                  get_value(method, 'InvSlabThick'))
        if isinstance(thickness, (int, float)):
            fields['LabelingSlabThickness'] = float(thickness)
    else:
        duration = get_value(method, 'CASL_LabelTime')
        if isinstance(duration, (int, float)):
            fields['LabelingDuration'] = duration / 1000.0

    delay = post_labeling_delay(kind, method, visu_pars, types)
    if delay is not None:
        fields['PostLabelingDelay'] = delay

    # REQUIRED for perf, and the generic mapping does not cover it: that one reads
    # SegmRepTime, which only a magnetization-prepared method declares. Emitted as a
    # scalar -- an array is checked against the aslcontext row count, and the
    # sequence TR does not vary per volume here.
    preparation = _first_number(get_value(visu_pars, 'VisuAcqRepetitionTime'),
                                get_value(method, 'PVM_RepetitionTime'))
    if preparation is not None:
        fields['RepetitionTimePreparation'] = preparation / 1000.0

    # REQUIRED for 2D ASL (SLICE_TIMING_NOT_DEFINED_2D_ASL is an error). The generic
    # mapping deliberately skips single-slice scans, where the derived order would be
    # meaningless -- but a single slice does have a timing, and it is zero.
    if n_slices == 1:
        fields['SliceTiming'] = [0.0]

    voxel = acquisition_voxel_size(method)
    if voxel:
        fields['AcquisitionVoxelSize'] = voxel
    return {k: v for k, v in fields.items() if v is not None}


def acquisition_voxel_size(method):
    """``[x, y, z]`` in mm, or None.

    PVM_SpatResol is already anti-alias corrected, so it is used directly rather
    than derived from FOV and matrix. In 2D the through-plane size is the slice
    thickness; in 3D PVM_SpatResol carries all three, and PVM_SliceThick is the
    whole SLAB -- reading it there would be wrong by the number of partitions.
    """
    resolution = get_value(method, 'PVM_SpatResol')
    if resolution is None:
        return None
    values = [float(v) for v in np.atleast_1d(resolution)]
    if len(values) >= 3:
        return values[:3]
    thickness = _first_number(get_value(method, 'PVM_SliceThick'))
    return [*values[:2], thickness] if len(values) == 2 and thickness else None


def post_labeling_delay(kind, method, visu_pars, types):
    """Post-labeling delay in seconds: one number, or one per volume.

    For FAIR the delay is the inversion time, and a multi-TI scan has a different
    one per volume -- so it is expanded to match the written volumes, which is what
    the validator checks it against. The TI list runs along the movie axis while
    control/label runs along the inversion axis, so the value repeats across the
    label pair rather than being listed once.
    """
    if kind == 'CASL':
        value = get_value(method, 'CASL_PostLabelTime')
        return value / 1000.0 if isinstance(value, (int, float)) else None

    inversion = get_value(visu_pars, 'VisuAcqInversionTime')
    if inversion is None:
        return None
    values = [float(v) / 1000.0 for v in np.atleast_1d(inversion)]
    if len(values) == 1:
        return values[0]
    if len(types) % len(values):
        return None
    # The written order is what volume_types already resolved; the TI list is in
    # acquisition order along its own axis, so tile it to the volume count.
    repeats = len(types) // len(values)
    return [v for _ in range(repeats) for v in values] if repeats > 1 else values


def volume_types(visu_pars):
    """One BIDS ``volume_type`` per written volume, in file order.

    The converter flattens the non-slice frame axes in Fortran order, so the first
    declared axis varies fastest. That is what makes the ``PVM_FairMode``
    ``INTERLEAVED2`` case -- where the inversion-mode axis is declared first --
    alternate control/label instead of running in blocks.
    """
    found = labelling_axis(visu_pars)
    if found is None:
        return None
    position, types = found
    sizes = [size for _, size in _axes(visu_pars)]
    total = int(np.prod(sizes))
    return [types[np.unravel_index(v, sizes, order='F')[position]] for v in range(total)]
