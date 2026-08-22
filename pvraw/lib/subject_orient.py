"""Canonical subject-position and subject-type handling.

Single source of truth for the pose/type table used by the one affine
implementation, ``pvraw.api.analyzer.affine.AffineAnalyzer`` (reached by
the ``app.tonifti`` API and, through it, the ``BrukerLoader`` / ``tonii`` CLI).

A now-deleted second implementation (``pvraw.lib.orient``, used by the
legacy loader path) once carried an independent copy of the table below, which
is how the two drifted apart (that copy gave ``Foot_Left``/``Foot_Right`` the
*head-first* rotation).  Keep the table here only.

What the position rotation is
-----------------------------
`brukerapi`'s affine is built from ``VisuCoreOrientation``/``VisuCorePosition``,
which ParaVision writes in the DICOM patient frame of the position it was
*told* -- ``VisuSubjectPosition`` / ``ACQ_patient_pos``. (``GTB_ObjPosMatrix``
in ``PvGeoTools.h`` "converts magnet coordinate system into object coordinate
system", keyed by that position.) So that affine is already anatomical, but
only for the *declared* position. Preclinical data routinely keeps ParaVision's
default ``Head_Supine`` on an animal lying prone -- 2,589 of 3,009 ``visu_pars``
in ``resources/testdata`` declare ``Head_Supine`` -- so pvraw does not trust
the declaration. It assumes the animal lay prone, head first
(``ASSUMED_POSITION``) unless ``--position`` says otherwise, and rotates the
declared frame into the actual one::

    correction = R(actual).T @ R(declared)

where ``R(pose)`` (``SUBJECT_POSE_ROTATION``) takes the frame ParaVision writes
for ``pose`` to the frame it writes for ``Head_Prone``, the reference. With no
override the correction is ``R(declared)``.

Verified on two SAMRI mouse studies from one lab, both animals prone, one
declared ``Head_Supine`` (``20151208_182500_4007_1_4``) and one ``Head_Prone``
(``20180730_053743_6587_1_1``): their `brukerapi` frames differ by a half turn
about F->H, and the corrected output is oriented the same, and correctly, for
both (reviewed 2026-08-21; ADR 0001, amendment of that date).

References
----------
ParaVision 6.0.1 Software Manual, S1.3.6 "Subject Coordinate Systems":

    Rodent (quadrupeds)      Ventral/Dorsal, Left/Right, Caudal/Rostral
    Primate (bipeds)         Anterior/Posterior, Left/Right, Head/Foot
                             "This coordinate system is also used for subject
                             specimen Unknown."
    Material (phantoms)      XYZ

ParaVision 5.1 D13 / 6.0.1 D02 "ParaVision Parameters", ``ACQ_patient_pos``:
``Head_Supine`` negates Gx and Gz; ``Head_Prone`` Gy and Gz; ``Head_Left``
negates Gz and exchanges Gx/Gy; ``Head_Right`` negates all three and exchanges
Gx/Gy; ``Foot_Supine`` leaves all unchanged; ``Foot_Prone`` negates Gx and Gy;
``Foot_Left`` negates Gy and exchanges Gx/Gy; ``Foot_Right`` negates Gx and
exchanges Gx/Gy. Read as ``subject = M_pose @ magnet`` every entry matches its
name (the ``*_Left`` matrices put the left side down), and
``R(pose) = M_Head_Prone @ M_pose.T``. FILE_FORMAT.md Section 12.
"""

import numpy as np

SUBJECT_TYPES = ['Biped', 'Quadruped', 'Phantom', 'Other', 'OtherAnimal']
SUBJECT_POSE = {
    'part': ['Head', 'Foot', 'Tail'],
    'side': ['Supine', 'Prone', 'Left', 'Right'],
}

#: The position pvraw assumes the animal was actually in when ``--position``
#: is not given: prone, head first -- the preclinical standard. The declared
#: position is what ParaVision was told, and is usually the untouched default.
ASSUMED_POSITION = 'Head_Prone'

#: ``Human`` is the ParaVision 5 spelling of the biped type. Accepted so an
#: explicit override (``--subjecttype Human``) works, but note that PV5 writes
#: ``SUBJECT_type=Human`` unconditionally, so it must never be read off a PV5
#: study as if it were a real declaration -- see ``uses_quadruped_frame``.
_TYPE_ALIASES = {'Human': 'Biped'}

#: ``R(pose)``: the rotation taking the frame ParaVision writes for ``pose`` to
#: the frame it writes for ``Head_Prone`` (the reference, identity). Derived as
#: ``M_Head_Prone @ M_pose.T`` from the manual's ``ACQ_patient_pos`` table
#: (module docstring).
#:
#: Supine/Prone/Left/Right differ by a roll about the bore (head-foot) axis.
#: Feet-first entry is the head-first rotation composed with a 180 degree flip
#: about the table-normal axis, i.e. ``Foot_X == Ry(pi) @ Head_X`` -- which is
#: why every ``Foot_*``/``Tail_*`` entry carries ``rad_y=pi``.  Angles are
#: consumed by ``apply_rotate``/``rotate_affine``, which compose as Rz @ Ry @ Rx
#: in the fixed frame.
#:
#: ``Head_Supine``/``Head_Prone`` are verified on data. No acquisition in the
#: corpus declares a ``*_Left``/``*_Right`` or ``Foot_*`` position, so those
#: entries rest on the manual alone (before 2026-08-21 the quarter turns had the
#: opposite sign, without a source).
SUBJECT_POSE_ROTATION = {
    'Head_Supine': {'rad_z': np.pi},
    'Head_Prone':  {},
    'Head_Left':   {'rad_z': -np.pi / 2},
    'Head_Right':  {'rad_z': np.pi / 2},
    'Foot_Supine': {'rad_x': np.pi},
    'Foot_Prone':  {'rad_y': np.pi},
    'Foot_Left':   {'rad_y': np.pi, 'rad_z': np.pi / 2},
    'Foot_Right':  {'rad_y': np.pi, 'rad_z': -np.pi / 2},
}

# Bruker uses Tail_* as the quadruped spelling of Foot_*.
for _side in SUBJECT_POSE['side']:
    SUBJECT_POSE_ROTATION[f'Tail_{_side}'] = SUBJECT_POSE_ROTATION[f'Foot_{_side}']
del _side


def normalize_subject_type(subj_type):
    """Map a raw subject type onto the ``VisuSubjectType`` vocabulary.

    Args:
        subj_type (str or None): value of ``VisuSubjectType`` (PV6+) or of the
            study-level ``SUBJECT_type`` (all versions).

    Returns:
        str or None: normalized type, or None if nothing was given.
    """
    if subj_type is None:
        return None
    return _TYPE_ALIASES.get(subj_type, subj_type)


def uses_quadruped_frame(subj_type):
    """Whether the rodent (quadruped) axis correction applies.

    An absent type selects the rodent correction. That looks wrong next to the
    PV6 manual (S1.3.6.2 says the Primate system "is also used for subject
    specimen Unknown"), but the manual is describing ParaVision's own display
    convention, not what a converter should do with PV5 data. Do not "fix" it
    to biped without re-running the validation below.

    ``VisuSubjectType`` exists only from PV6 onwards. ParaVision 5.1 cannot
    express a subject type at all -- it writes ``SUBJECT_type=Human`` for every
    study regardless of the actual specimen -- so on PV5 the type is genuinely
    unknown, and preclinical PV5 data is overwhelmingly rodent.

    Verified against paired PV5.1/PV6.0.1 acquisitions of the same mouse
    phantom, scanned head-first prone on both systems (PV5 declares ``Human``,
    PV6 declares ``Quadruped``). Resampling the PV5 volumes into the PV6
    reference grid:

        rodent axes (absent type -> quadruped)   NCC +0.90 .. +0.95
        primate axes (absent type -> biped)      NCC +0.22

    across four matched 3D FLASH pairs. Honouring the ``Human`` label puts PV5
    rodent data in the wrong frame, so the type must not be taken from the
    study-level ``SUBJECT_type`` either.

    Args:
        subj_type (str or None): raw or normalized subject type. None means
            unknown, which is treated as non-biped.

    Returns:
        bool: False only when the type is positively known to be a biped.
    """
    return normalize_subject_type(subj_type) != 'Biped'


def get_pose_rotation(subj_pose):
    """Rotation angles ``R(pose)`` for a ``VisuSubjectPosition`` value.

    Takes the frame ParaVision writes for ``subj_pose`` to the one it writes
    for ``Head_Prone``; see the module docstring for how the declared and the
    actual position compose.

    Args:
        subj_pose (str or None): e.g. ``'Head_Supine'``. None/empty yields no
            rotation.

    Returns:
        dict: kwargs for ``apply_rotate``/``rotate_affine``.

    Raises:
        KeyError: if the position is not one Bruker defines.
    """
    if not subj_pose:
        return {}
    return dict(SUBJECT_POSE_ROTATION[subj_pose])


def inspect_subject_info(subj_pose, subj_type):
    """Validate subject position/type strings.

    Raises:
        AssertionError: on a malformed position or an unknown type.
    """
    if subj_pose:
        part, side = subj_pose.split('_')
        assert part in SUBJECT_POSE['part'], 'Invalid subject position'
        assert side in SUBJECT_POSE['side'], 'Invalid subject position'
    if subj_type:
        assert normalize_subject_type(subj_type) in SUBJECT_TYPES, 'Invalid subject type'
