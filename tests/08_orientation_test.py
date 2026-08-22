"""Subject orientation regression tests.

Covers the defect found by reviewing the affine code against the Bruker
ParaVision orientation conventions: ``Foot_Left``/``Foot_Right`` (and their
``Tail_*`` aliases) were once given the *head-first* rotation, dropping the
feet-first entry flip. There is now a single affine implementation
(``AffineAnalyzer``); these tests pin its pose/type behaviour directly.

The pose table is pinned to the manual's ``ACQ_patient_pos`` definition
(``MANUAL`` below) and the declared/actual composition of ADR 0001 (as amended
2026-08-21): the recorded position is what ParaVision was told and the frame
the Visu geometry is written in; the correction rotates it into the frame of
the position the animal was actually in, ``Head_Prone`` unless ``--position``
says otherwise.

Also pins the subject-type behaviour that ParaVision's display convention makes
look wrong. The Primate system "is also used for subject specimen Unknown",
which reads as though an absent ``VisuSubjectType`` (i.e. all PV5 data) should
use the biped frame. Changing it to that regresses real PV5 rodent conversions;
see ``test_absent_subject_type_uses_rodent_frame`` for the evidence.
"""
import numpy as np
import pytest

from pvraw.api.analyzer.affine import AffineAnalyzer
from pvraw.api.helper import rotate_affine
from pvraw.lib.subject_orient import (
    SUBJECT_POSE_ROTATION,
    get_pose_rotation,
    normalize_subject_type,
    uses_quadruped_frame,
)

PI = np.pi
SIDES = ['Supine', 'Prone', 'Left', 'Right']


#: Head_Prone is the reference (identity). The other head-first poses differ by
#: a roll about the bore/head-foot axis (signs from MANUAL below).
HEAD_FIRST = {
    'Prone': {},
    'Supine': {'rad_z': PI},
    'Left': {'rad_z': -PI / 2},
    'Right': {'rad_z': PI / 2},
}

#: ``ACQ_patient_pos`` as the PV5.1 D13 / PV6 D02 manuals define it -- how each
#: position negates and exchanges the gradient axes -- read as
#: ``subject = M_pose @ magnet`` (ParaVision's ``GTB_ObjPosMatrix``). Row 0 is
#: the subject's right: for every ``*_Left`` it points up, i.e. left side down,
#: so each entry matches its name; and ``Foot_X == Head_X @ Ry(pi)``, the
#: end-for-end turn about the vertical.
MANUAL = {
    'Head_Supine': np.diag([-1, 1, -1]),                            # negates Gx and Gz
    'Head_Prone':  np.diag([1, -1, -1]),                            # negates Gy and Gz
    'Head_Left':   np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]]),    # negates Gz, exchanges Gx/Gy
    'Head_Right':  np.array([[0, -1, 0], [-1, 0, 0], [0, 0, -1]]),  # negates all, exchanges Gx/Gy
    'Foot_Supine': np.eye(3),                                       # unchanged
    'Foot_Prone':  np.diag([-1, -1, 1]),                            # negates Gx and Gy
    'Foot_Left':   np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]]),    # negates Gy, exchanges Gx/Gy
    'Foot_Right':  np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]]),    # negates Gx, exchanges Gx/Gy
}


def _rot(**kwargs):
    """3x3 rotation, same composition as rotate_affine (Rz @ Ry @ Rx)."""
    return rotate_affine(np.eye(4), **kwargs)[:3, :3]


def _expected(pose):
    """Derived truth: Foot_X == Ry(pi) @ Head_X (180 deg end-for-end entry flip)."""
    part, side = pose.split('_')
    head = _rot(**HEAD_FIRST[side])
    if part == 'Head':
        return head
    return _rot(rad_y=PI) @ head


ALL_POSES = [f'{p}_{s}' for p in ('Head', 'Foot', 'Tail') for s in SIDES]


@pytest.mark.parametrize('pose', ALL_POSES)
def test_pose_rotation_matches_derivation(pose):
    """Every defined pose must equal the geometrically derived rotation."""
    assert np.allclose(_rot(**get_pose_rotation(pose)), _expected(pose), atol=1e-9)


@pytest.mark.parametrize('side', SIDES)
def test_feet_first_differs_from_head_first(side):
    """Regression: feet-first must not reuse the head-first rotation.

    ``Foot_Left``/``Foot_Right`` previously shared the ``Head_*`` rotation,
    which silently mislabels left/right for feet-first acquisitions.
    """
    head = _rot(**get_pose_rotation(f'Head_{side}'))
    foot = _rot(**get_pose_rotation(f'Foot_{side}'))
    assert not np.allclose(head, foot, atol=1e-9)


@pytest.mark.parametrize('side', SIDES)
def test_tail_is_alias_of_foot(side):
    """Bruker spells the quadruped feet-first entry Tail_*."""
    assert (SUBJECT_POSE_ROTATION[f'Tail_{side}']
            == SUBJECT_POSE_ROTATION[f'Foot_{side}'])


@pytest.mark.parametrize('pose', ALL_POSES)
def test_both_code_paths_agree(pose):
    """The legacy loader path and the API path must not drift apart again.

    These carried independent copies of the pose table, which is how they came
    to disagree on Foot_Left/Foot_Right in the first place.
    """
    api = AffineAnalyzer._est_rotate_angle(pose)
    lib = {'rad_x': 0, 'rad_y': 0, 'rad_z': 0}
    lib.update(get_pose_rotation(pose))
    assert np.allclose(_rot(**api), _rot(**lib), atol=1e-9)


def test_rotations_are_proper_rotations():
    """No pose may introduce a reflection (det must be +1, not -1)."""
    for pose in ALL_POSES:
        assert np.isclose(np.linalg.det(_rot(**get_pose_rotation(pose))), 1.0, atol=1e-9)


def test_unknown_pose_raises():
    with pytest.raises(KeyError):
        get_pose_rotation('Head_Sideways')


def test_empty_pose_is_identity():
    assert get_pose_rotation(None) == {}
    assert get_pose_rotation('') == {}


@pytest.mark.parametrize('pose', list(MANUAL))
def test_pose_rotation_matches_the_manual(pose):
    """R(pose) = M_Head_Prone @ M_pose.T: declared-pose frame -> Head_Prone frame.

    The manual's per-position matrices are the magnet -> subject map, so the
    frame ParaVision writes for ``pose`` and the one it writes for
    ``Head_Prone`` are related by exactly this. The quarter turns had the
    opposite sign before 2026-08-21, with no source.
    """
    want = MANUAL['Head_Prone'] @ MANUAL[pose].T
    assert np.allclose(_rot(**get_pose_rotation(pose)), want, atol=1e-9)


def test_manual_table_is_self_consistent():
    """Every manual entry is a proper rotation and Foot_X == Head_X @ Ry(pi)."""
    for m in MANUAL.values():
        assert np.isclose(np.linalg.det(m), 1.0)
    for side in SIDES:
        assert np.array_equal(MANUAL[f'Foot_{side}'], MANUAL[f'Head_{side}'] @ _rot(rad_y=PI).round())


# --- declared vs actual position ---------------------------------------------

def test_no_override_undoes_the_declaration():
    """With no --position the declared frame is rotated into the Head_Prone frame.

    The SAMRI case: a prone mouse declared Head_Supine comes out of Visu half a
    turn about F->H from one declared Head_Prone, and R(Head_Supine) = Rz(pi)
    brings it back. A Head_Prone declaration is left alone.
    """
    supine = AffineAnalyzer._correct_orientation(np.eye(4), 'Head_Supine', 'Biped')
    prone = AffineAnalyzer._correct_orientation(np.eye(4), 'Head_Prone', 'Biped')
    assert np.allclose(supine[:3, :3], _rot(rad_z=PI), atol=1e-9)
    assert np.allclose(prone, np.eye(4), atol=1e-9)


@pytest.mark.parametrize('declared', ALL_POSES)
@pytest.mark.parametrize('actual', ALL_POSES)
def test_override_is_the_actual_position(declared, actual):
    """--position X means 'the animal lay like X': rotation = R(X).T @ R(declared)."""
    got = AffineAnalyzer._correct_orientation(np.eye(4), declared, 'Biped', actual)[:3, :3]
    want = _rot(**get_pose_rotation(actual)).T @ _rot(**get_pose_rotation(declared))
    assert np.allclose(got, want, atol=1e-9)


@pytest.mark.parametrize('pose', ALL_POSES)
def test_override_equal_to_declared_trusts_the_file(pose):
    """Saying the animal lay as declared leaves brukerapi's (declared-frame) affine alone."""
    got = AffineAnalyzer._correct_orientation(np.eye(4), pose, 'Biped', pose)
    assert np.allclose(got, np.eye(4), atol=1e-9)


def test_override_default_equals_head_prone():
    """No override and an explicit Head_Prone must agree, to the bit."""
    aff = rotate_affine(np.eye(4), rad_x=0.3, rad_y=-0.2, rad_z=1.1)
    aff[:3, 3] = [1.5, -2.5, 3.5]
    for declared in ALL_POSES:
        default = AffineAnalyzer._correct_orientation(aff, declared, 'Quadruped')
        explicit = AffineAnalyzer._correct_orientation(aff, declared, 'Quadruped', 'Head_Prone')
        assert np.array_equal(default, explicit)


# --- subject type -------------------------------------------------------

def test_absent_subject_type_uses_rodent_frame():
    """Unknown subject type must keep the rodent correction.

    VisuSubjectType exists only from PV6 onwards, and PV5 cannot express a
    subject type at all (it writes SUBJECT_type=Human for every study), so on
    PV5 the type is genuinely unknown and the data is overwhelmingly rodent.

    Validated against paired PV5.1/PV6.0.1 acquisitions of the same mouse
    phantom (head-first prone): they agree at NCC +0.90..+0.95 under the rodent
    frame and only +0.22 under the primate frame. ParaVision's "Unknown ->
    Primate" rule describes its display convention, not what a converter should
    do here.
    """
    assert uses_quadruped_frame(None) is True


def test_explicit_human_override_is_biped():
    """'Human' is accepted as the PV5 spelling of Biped for explicit overrides.

    This is only for a user-supplied --subjecttype. It must never be read off a
    PV5 study automatically: see test_pv5_subject_type_not_taken_from_subject_file.
    """
    assert normalize_subject_type('Human') == 'Biped'
    assert uses_quadruped_frame('Human') is False


@pytest.mark.parametrize('subj_type', ['Quadruped', 'Other', 'OtherAnimal', 'Phantom'])
def test_non_biped_types_still_corrected(subj_type):
    """Existing behaviour for known non-biped types is unchanged."""
    assert uses_quadruped_frame(subj_type) is True


def test_pv5_subject_type_not_taken_from_subject_file(h2_study):
    """The loader must not read subject type off a PV5 study.

    PV5 writes SUBJECT_type=Human unconditionally, so the resolved type must
    stay None (unknown -> rodent) rather than becoming Biped. The single affine
    implementation reads VisuSubjectType per-scan (absent on PV5, FILE_FORMAT.md
    7.5), never the study subject file; this pins that.
    """
    from pvraw import BrukerLoader
    from pvraw.app.tonifti import StudyToNifti

    s = BrukerLoader(str(h2_study))
    assert s.subj_type == 'Human', 'expected the PV5 subject file to say Human'
    sid = s.avail_scan_id[0]
    study = StudyToNifti(str(h2_study))
    analyzer = study.get_scan(sid).get_affine_analyzer(1)
    assert analyzer.subj_type is None, (
        'PV5 subject type must stay unknown, not be read from SUBJECT_type')
    assert uses_quadruped_frame(analyzer.subj_type) is True


def test_biped_not_corrected():
    assert uses_quadruped_frame('Biped') is False


def test_quadruped_correction_applied_after_pose():
    """The animal correction is a fixed-frame convention change.

    It must left-multiply the pose rotation (Q @ P), not be folded into it,
    otherwise the pose angles would be interpreted in already-rotated axes --
    the failure mode reported upstream in BrkRaw/brkraw#228. Exercised on the
    single affine implementation, ``AffineAnalyzer._correct_orientation``, with
    the ParaVision subject types Biped/Quadruped (FILE_FORMAT.md 7.5).
    """
    biped = AffineAnalyzer._correct_orientation(np.eye(4), 'Head_Supine', 'Biped')
    quad = AffineAnalyzer._correct_orientation(np.eye(4), 'Head_Supine', 'Quadruped')
    q = rotate_affine(np.eye(4), rad_x=-PI / 2, rad_y=PI)[:3, :3]
    assert np.allclose(quad[:3, :3], q @ biped[:3, :3], atol=1e-9)


# --- API path on real data -------------------------------------------------

def test_unequal_slices_per_pack_converts(lego_study):
    """Unequal per-pack slice counts must convert to one affine per pack.

    lego_phantom scan 8 is a 13-frame scout genuinely packed [5, 3, 5]. The
    SlicePack parser (VisuCoreSlicePacksSlices per-pack counts, FILE_FORMAT.md
    7.10) and the frame regrouping in Orientation must use those counts rather
    than assuming an equal split; otherwise assembly crashes. Each pack yields a
    (4, 4) affine.
    """
    from pvraw.app.tonifti import StudyToNifti

    api = StudyToNifti(str(lego_study)).get_affine(8, 1)
    assert isinstance(api, list) and len(api) == 3
    for aff in api:
        assert np.shape(aff) == (4, 4)
