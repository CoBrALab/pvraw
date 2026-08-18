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
    """Places a reconstruction in the subject's frame.

    The voxel-to-patient affine comes from `brukerapi`, which derives it from
    ``VisuCorePosition``/``VisuCoreOrientation`` per FILE_FORMAT.md 7.2 (ADR
    0002, amended). What this class adds is the part `brukerapi` deliberately
    leaves out: the subject-type and subject-position corrections of ADR 0001
    (as amended), which the CLI can override per scan.

    Args:
        infoobj (ScanInfo): Analysed scan properties; supplies the subject type
            and position when the caller does not override them.
        dataset: The `brukerapi` Dataset for the reconstruction.

    Attributes:
        affine: The patient-frame affine, or one per slice package.
        subj_type (str): The type of the subject (e.g., Biped, Quadruped).
        subj_position (str): The position of the subject during the scan.
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
        """Retrieve the affine matrix, applying corrections based on subject type and position.
        """
        subj_type = subj_type or self.subj_type
        subj_position = subj_position or self.subj_position
        if isinstance(self.affine, list):
            return [self._correct_orientation(aff, subj_position, subj_type) for aff in self.affine]
        return self._correct_orientation(self.affine, subj_position, subj_type)

    @staticmethod
    def _est_rotate_angle(subj_pose):
        """Estimate the rotation angle needed based on the subject's pose.
        """
        rotate_angle = {'rad_x': 0, 'rad_y': 0, 'rad_z': 0}
        try:
            rotate_angle.update(get_pose_rotation(subj_pose))
        except KeyError:
            raise NotImplementedError
        return rotate_angle

    @classmethod
    def _correct_orientation(cls, affine, subj_pose, subj_type):
        """Correct the orientation of the affine matrix based on the subject's type and pose.
        """
        cls._inspect_subj_info(subj_pose, subj_type)
        rotate_angle = cls._est_rotate_angle(subj_pose)
        affine = helper.rotate_affine(affine, **rotate_angle)

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
