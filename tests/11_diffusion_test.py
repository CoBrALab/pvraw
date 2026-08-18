"""Unit tests for DWI b-vector reorientation (lib/loader._reorient_bvecs).

Pure-unit (offline): _reorient_bvecs is a staticmethod over (bvecs, affine), so
no dataset is needed.
"""
import numpy as np

from pvraw.lib.loader import BrukerLoader


def test_reorient_bvecs_axis_aligned_is_noop():
    """An axis-aligned affine leaves the b-vectors unchanged (H3).

    Only oblique acquisitions are rotated, so the common (axis-aligned) case is
    never regressed.
    """
    bvecs = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], float).T   # (3, 3)
    affine = np.diag([0.2, 0.2, 0.5, 1.0])
    out = BrukerLoader._reorient_bvecs(bvecs, affine)
    assert np.allclose(out, bvecs)


def test_reorient_bvecs_follows_oblique_rotation():
    """A rotated affine reorients the vectors into the voxel frame (R^T @ g)."""
    R = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)        # 90deg about z: voxel->world
    affine = np.eye(4)
    affine[:3, :3] = R * 0.3                                       # include voxel scaling
    g_world_x = np.array([[1.0], [0.0], [0.0]])                    # a gradient along world +x
    out = BrukerLoader._reorient_bvecs(g_world_x, affine)
    assert np.allclose(out.ravel(), [0.0, -1.0, 0.0])             # -> voxel -y


def test_reorient_bvecs_preserves_unit_norm():
    """Reorientation is a rotation, so unit b-vectors stay unit length."""
    theta = 0.7
    R = np.array([[np.cos(theta), -np.sin(theta), 0],
                  [np.sin(theta), np.cos(theta), 0],
                  [0, 0, 1]], float)
    affine = np.eye(4)
    affine[:3, :3] = R * 0.4
    bvecs = np.array([[1, 0, 0], [0, 1, 0], [1, 1, 1]], float).T
    bvecs = bvecs / np.linalg.norm(bvecs, axis=0)
    out = BrukerLoader._reorient_bvecs(bvecs, affine)
    assert np.allclose(np.linalg.norm(out, axis=0), 1.0)
