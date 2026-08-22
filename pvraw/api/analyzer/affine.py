"""Affine Matrix Analyzer Module.

This module focuses on analyzing and processing affine matrices derived from imaging data.
It provides functionalities to calculate, adjust, and standardize affine transformations based
on specific imaging parameters and subject orientations, thereby facilitating accurate spatial
orientation and alignment of imaging data.
"""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING

import numpy as np

from pvraw.api import helper
from pvraw.lib.subject_orient import (
    ASSUMED_POSITION,
    SUBJECT_POSE,
    SUBJECT_TYPES,
    get_pose_rotation,
    inspect_subject_info,
    uses_quadruped_frame,
)

from .base import BaseAnalyzer

if TYPE_CHECKING:
    from ..data.scan import ScanInfo


# Retained as module-level aliases for backwards compatibility; the canonical
# definitions live in pvraw.lib.subject_orient.
SUBJTYPE = SUBJECT_TYPES
SUBJPOSE = SUBJECT_POSE


class AffineAnalyzer(BaseAnalyzer):
    """Places a reconstruction in the frame of the animal as it actually lay.

    The voxel-to-patient affine comes from `brukerapi`, which derives it from
    ``VisuCorePosition``/``VisuCoreOrientation`` per FILE_FORMAT.md 7.2 (ADR
    0002, amended). ParaVision writes those in the DICOM frame of the position
    it was *told* (``VisuSubjectPosition``), so that affine is anatomical for
    the declared position only. What this class adds (ADR 0001, as amended
    2026-08-21) is the rotation from the declared position to the actual one
    -- pvraw assumes ``Head_Prone`` unless ``--position`` says otherwise,
    because ParaVision's default ``Head_Supine`` is routinely left on prone
    rodents -- and the quadruped axis convention. Both can be overridden per
    scan (``--position``, ``--subjecttype``). See ``lib/subject_orient.py``.

    Args:
        infoobj (ScanInfo): Analysed scan properties; supplies the declared
            subject type and position.
        dataset: The `brukerapi` Dataset for the reconstruction.

    Attributes:
        affine: The patient-frame affine, or one per slice package.
        subj_type (str): ``VisuSubjectType`` (e.g., Biped, Quadruped).
        subj_position (str): ``VisuSubjectPosition`` -- the declared position.
    """
    def __init__(self, infoobj: ScanInfo, dataset):
        infoobj = copy(infoobj)
        packs = infoobj.slicepack['num_slice_packs']
        if packs > 1:
            # More than one package means more than one geometry, so each gets
            # its own affine -- and its own image downstream. Asked for by index
            # rather than through `slice_packages`, which splits the array and
            # so would read the 2dseq just to place it.
            self.affine = [np.asarray(dataset.affine_of_package(i), dtype=float)
                           for i in range(packs)]
        else:
            self.affine = np.asarray(dataset.affine_of_package(0), dtype=float)

        self.subj_type = infoobj.orientation['subject_type'] if hasattr(infoobj, 'orientation') else None
        self.subj_position = infoobj.orientation['subject_position'] if hasattr(infoobj, 'orientation') else None

    def get_affine(self, subj_type: str | None = None, subj_position: str | None = None):
        """The affine in the frame of the animal as it actually lay.

        Args:
            subj_type: overrides ``VisuSubjectType`` (the quadruped convention).
            subj_position: the position the animal was actually in
                (``Head_Prone``, ``Foot_Supine``, ...). None assumes
                ``ASSUMED_POSITION``. The *declared* position is always the
                scan's own ``VisuSubjectPosition``.
        """
        subj_type = subj_type or self.subj_type
        if isinstance(self.affine, list):
            return [self._correct_orientation(aff, self.subj_position, subj_type, subj_position)
                    for aff in self.affine]
        return self._correct_orientation(self.affine, self.subj_position, subj_type, subj_position)

    @staticmethod
    def _est_rotate_angle(subj_pose):
        """``R(pose)`` as rotate_affine angles: declared-pose frame -> Head_Prone frame.
        """
        rotate_angle = {'rad_x': 0, 'rad_y': 0, 'rad_z': 0}
        try:
            rotate_angle.update(get_pose_rotation(subj_pose))
        except KeyError:
            raise NotImplementedError
        return rotate_angle

    @classmethod
    def _pose_rotation(cls, subj_pose):
        """``R(pose)`` as a 3x3 matrix."""
        return helper.rotate_affine(np.eye(4), **cls._est_rotate_angle(subj_pose))[:3, :3]

    @classmethod
    def _correct_orientation(cls, affine, subj_pose, subj_type, actual_pose=None):
        """Rotate the declared position's frame into the actual position's frame.

        ``subj_pose`` is what ParaVision was told (``VisuSubjectPosition``),
        the frame `brukerapi`'s affine is in; ``actual_pose`` is how the animal
        lay (``--position``), ``ASSUMED_POSITION`` when not given. The rotation
        is ``R(actual).T @ R(declared)`` -- with the default it is
        ``R(declared)``, which undoes the declaration and asserts prone/head
        first. The quadruped convention change follows, as a fixed-frame
        rotation (left-multiplied, never folded into the pose angles).
        """
        cls._inspect_subj_info(subj_pose, subj_type)
        cls._inspect_subj_info(actual_pose, None)
        rot = cls._pose_rotation(actual_pose or ASSUMED_POSITION).T @ cls._pose_rotation(subj_pose)
        mat, vec = helper.to_matvec(affine)
        affine = helper.from_matvec(rot @ mat, rot @ vec)

        if uses_quadruped_frame(subj_type):
            # fixed-frame Primate -> Rodent axis convention change; independent
            # of subject pose, hence applied after the pose rotation.
            affine = helper.rotate_affine(affine, rad_x=-np.pi/2, rad_y=np.pi)
        return affine

    @staticmethod
    def _inspect_subj_info(subj_pose, subj_type):
        """Validate subject type and pose information.
        """
        inspect_subject_info(subj_pose, subj_type)
