"""Affine Matrix Analyzer Module.

This module focuses on analyzing and processing affine matrices derived from imaging data.
It provides functionalities to calculate, adjust, and standardize affine transformations based
on specific imaging parameters and subject orientations, thereby facilitating accurate spatial
orientation and alignment of imaging data.
"""

from __future__ import annotations
from brkraw_legacy.api import helper
from brkraw_legacy.lib.subject_orient import (
    SUBJECT_TYPES,
    SUBJECT_POSE,
    get_pose_rotation,
    inspect_subject_info,
    uses_quadruped_frame,
)
from .base import BaseAnalyzer
import numpy as np
from copy import copy
from typing import TYPE_CHECKING, Optional
if TYPE_CHECKING:
    from ..data.scan import ScanInfo


SLICEORIENT = {
    0: 'sagital',
    1: 'coronal',
    2: 'axial'
    }

# Retained as module-level aliases for backwards compatibility; the canonical
# definitions live in brkraw_legacy.lib.subject_orient.
SUBJTYPE = SUBJECT_TYPES
SUBJPOSE = SUBJECT_POSE


class AffineAnalyzer(BaseAnalyzer):
    """Processes affine matrices from raw dataset parameters to ensure proper spatial orientation.

    This analyzer calculates affine matrices based on imaging data and subject configurations.
    It supports various adjustments based on subject type and pose, ensuring the matrices are
    suitable for specific analysis and visualization requirements.

    Args:
        infoobj (ScanInfo): The information object containing imaging parameters and subject orientation.

    Attributes:
        resolution (list[tuple]): Resolution details extracted from imaging data.
        affine (np.ndarray or list[np.ndarray]): The calculated affine matrices.
        subj_type (str): The type of the subject (e.g., Biped, Quadruped).
        subj_position (str): The position of the subject during the scan.
    """
    def __init__(self, infoobj: 'ScanInfo'):
        """Initialize the AffineAnalyzer with an information object.
        """
        infoobj = copy(infoobj)
        if infoobj.image['dim'] == 2:
            xr, yr = infoobj.image['resolution']
            self.resolution = [(xr, yr, zr) for zr in infoobj.slicepack['slice_distances_each_pack']]
        elif infoobj.image['dim'] == 3:
            self.resolution = [infoobj.image['resolution'][:]]
        else:
            raise NotImplementedError
        if infoobj.slicepack['num_slice_packs'] > 1:
            self.affine = [
                self._calculate_affine(infoobj, slicepack_id)
                for slicepack_id in range(infoobj.slicepack['num_slice_packs'])
            ]
        else:
            self.affine = self._calculate_affine(infoobj)
        
        self.subj_type = infoobj.orientation['subject_type'] if hasattr(infoobj, 'orientation') else None
        self.subj_position = infoobj.orientation['subject_position'] if hasattr(infoobj, 'orientation') else None
        
    def get_affine(self, subj_type: Optional[str] = None, subj_position: Optional[str] = None):
        """Retrieve the affine matrix, applying corrections based on subject type and position.
        """
        subj_type = subj_type or self.subj_type
        subj_position = subj_position or self.subj_position
        if isinstance(self.affine, list):
            affine = [self._correct_orientation(aff, subj_position, subj_type) for aff in self.affine]
        elif isinstance(self.affine, np.ndarray):
            affine = self._correct_orientation(self.affine, subj_position, subj_type)
        return affine
            
    def _calculate_affine(self, infoobj: 'ScanInfo', slicepack_id: Optional[int] = None):
        """Calculate the initial affine matrix based on the imaging data and subject orientation.
        """
        # slicepack_id is None for a single-pack scan (orientation/volume_origin
        # are bare values) and an int for one pack of a multi-pack scan (they are
        # lists indexed by pack). Test `is not None`, not truthiness: pack 0 is a
        # real pack, and treating it as the single-pack case reads a list-of-packs
        # as if it were one pack (crashing on localizers) and, for reverse slice
        # order, passes the whole distances list where a scalar is required.
        multi = slicepack_id is not None
        pack = slicepack_id if multi else 0
        orient_desc = infoobj.orientation['orientation_desc']
        sidx = (orient_desc[slicepack_id] if multi else orient_desc).index(2)
        slice_orient = SLICEORIENT[sidx]
        resol = self.resolution[pack]
        orientation = infoobj.orientation['orientation'][slicepack_id] \
            if multi else infoobj.orientation['orientation']
        volume_origin = infoobj.orientation['volume_origin'][slicepack_id] \
            if multi else infoobj.orientation['volume_origin']
        if infoobj.slicepack['reverse_slice_order']:
            # FILE_FORMAT.md 7.2: under disk_reverse_slice_order the frames are
            # stored against the orientation's third row, and VisuCorePosition
            # stops meaning "first voxel of the volume" -- for a 3D frame it is
            # the first voxel of the *last* stored 2D frame. The origin of
            # stored voxel (0,0,0) is therefore (N-1) steps away, not N: the
            # slab extent less one plane.
            #
            # Written as extent-minus-one-step so both cases fall out of one
            # expression. For a 3D frame resol[-1] is the plane step, giving
            # (N-1) steps. For a 2D multi-slice frame it *is* the slice
            # distance, giving zero -- correctly, because there the position
            # list already carries one entry per slice and needs no shift.
            slice_distance = infoobj.slicepack['slice_distances_each_pack'][pack]
            volume_origin = self._correct_origin(orientation, volume_origin,
                                                 slice_distance - resol[-1])
        return self._compose_affine(resol, orientation, volume_origin, slice_orient)

    @staticmethod
    def _correct_origin(orientation, volume_origin, slice_distance):
        """Adjust the origin of the volume based on slice orientation and distance.
        """
        new_origin = orientation.dot(volume_origin)
        new_origin[-1] += slice_distance
        return orientation.T.dot(new_origin)
    
    @staticmethod
    def _compose_affine(resolution, orientation, volume_origin, slice_orient):
        """Compose the affine transformation matrix using the provided resolution, orientation, and origin.
        """
        resol = np.array(resolution)
        if slice_orient in ['axial', 'sagital']:
            resol = np.diag(resol)
        else:
            resol = np.diag(resol * np.array([1, 1, -1]))
        
        rmat = orientation.T.dot(resol)
        return helper.from_matvec(rmat, volume_origin)
    
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
