from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from pvraw.lib.utils import get_value

from .base import BaseHelper

if TYPE_CHECKING:
    from ..analyzer import ScanInfoAnalyzer


def from_matvec(mat, vec):
    """Create an affine transformation matrix from a matrix and a vector."""
    if mat.shape == (3, 3) and vec.shape == (3,):
        affine = np.eye(4)
        affine[:3, :3] = mat
        affine[:3, 3] = vec
        return affine
    else:
        raise ValueError("Matrix must be 3x3 and vector must be 1x3")


def to_matvec(affine):
    """
    Decompose a 4x4 affine matrix into a 3x3 matrix and a 1x3 vector.

    Parameters:
    affine (numpy.ndarray): A 4x4 affine transformation matrix.

    Returns:
    tuple: A 3x3 matrix and a 1x3 vector.
    """
    if affine.shape != (4, 4):
        raise ValueError("Affine matrix must be 4x4")
    mat = affine[:3, :3]
    vec = affine[:3, 3]
    return mat, vec


def rotate_affine(affine, rad_x=0, rad_y=0, rad_z=0):
    ''' axis = x or y or z '''
    rmat = {'x': np.array([[1, 0, 0],
                           [0, np.cos(rad_x), -np.sin(rad_x)],
                           [0, np.sin(rad_x), np.cos(rad_x)]]).astype('float'),
            'y': np.array([[np.cos(rad_y), 0, np.sin(rad_y)],
                           [0, 1, 0],
                           [-np.sin(rad_y), 0, np.cos(rad_y)]]).astype('float'),
            'z': np.array([[np.cos(rad_z), -np.sin(rad_z), 0],
                           [np.sin(rad_z), np.cos(rad_z), 0],
                           [0, 0, 1]]).astype('float')}
    af_mat, af_vec = to_matvec(affine)
    rotated_mat = rmat['z'].dot(rmat['y'].dot(rmat['x'].dot(af_mat)))
    rotated_vec = rmat['z'].dot(rmat['y'].dot(rmat['x'].dot(af_vec)))
    return from_matvec(rotated_mat, rotated_vec)


class Orientation(BaseHelper):
    """What ParaVision was told about the subject: its type and its position.

    `brukerapi` derives the affine from ``VisuCorePosition``/
    ``VisuCoreOrientation`` (ADR 0002, amended), which ParaVision writes in the
    DICOM frame of the *declared* position -- so that affine must not apply
    ``VisuSubjectPosition`` again (a defect of the old upstream affine). What
    ADR 0001's correction (as amended 2026-08-21) does with these two
    parameters is different: it rotates the declared position's frame into the
    frame of the position the animal was actually in (``--position``, assumed
    ``Head_Prone``), and applies the quadruped convention by type
    (``--subjecttype``). See ``lib/subject_orient.py``.

    Dependencies:
        visu_pars
    """
    def __init__(self, analobj: ScanInfoAnalyzer):
        super().__init__()
        visu_pars = analobj.visu_pars
        self.subject_type = get_value(visu_pars, "VisuSubjectType")
        self.subject_position = get_value(visu_pars, "VisuSubjectPosition")

    def get_info(self):
        return {
            'subject_type': self.subject_type,
            'subject_position': self.subject_position,
            'warns': self.warns
        }
