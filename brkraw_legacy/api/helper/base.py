import warnings
from functools import partial

import numpy as np


def is_all_element_same(listobj):
    if listobj is None:
        return True
    else:
        return all(map(partial(lambda x, y: x == y, y=listobj[0]), listobj))


def axis_labels(dataset):
    """One lower-case name per axis of the reconstruction's image array.

    `brukerapi` names every axis: the encoded spatial axes from
    ``VisuCoreDimDesc``, then one per Frame Group (``FG_ECHO`` and so on).
    Strip the ``FG_`` prefix so the rest of the code reads ``echo``, ``slice``,
    ``diffusion``.

    Two axes need naming rather than renaming. A reconstruction with no frame
    groups carries a trailing size-1 ``frame`` placeholder, which is dropped --
    a 3D volume is ``(x, y, z)``, not ``(x, y, z, 1)``. A single-slice 2D
    acquisition carries an inserted size-1 third axis, which *is* the slice
    axis the affine's third column addresses, so it is named as one.
    """
    labels = []
    for name in dataset.dim_type:
        name = str(name)
        labels.append(name[3:].lower() if name.upper().startswith('FG_') else name.lower())
    if labels[-1:] == ['frame']:
        labels = labels[:-1]
    if dataset.get('is_single_slice', False) and len(labels) > 2:
        labels[2] = 'slice'
    return labels


def frame_groups(dataset):
    """``(name, size)`` for each Frame Group axis of the reconstruction.

    The spatial axes -- including the size-1 slice axis inserted for a
    single-slice acquisition, which is not a frame group -- are excluded, so
    this is the ParaVision Frame Group list with its sizes.
    """
    labels = axis_labels(dataset)
    sizes = tuple(dataset.shape_final)[:len(labels)]
    first = dataset.encoded_dim + (1 if dataset.get('is_single_slice', False) else 0)
    return list(zip(labels[first:], sizes[first:]))


def normalized_axes(labels, shape):
    """Axis names and sizes with the slice axis at position k (2).

    The affine's third column addresses k, so the slice axis has to be there
    and has to exist: a single-slice 2D acquisition stores no slice axis at
    all, and a 2D acquisition whose extra axes are frame groups would otherwise
    have those frames mistaken for slices. Returns new lists, leaving the
    inputs alone; ``BaseMethods._normalize_slice_axis`` moves the array to
    match.
    """
    labels, shape = list(labels), list(shape)
    if 'slice' in labels:
        axis = labels.index('slice')
        if axis != 2:
            labels[axis], labels[2] = labels[2], labels[axis]
            shape[axis], shape[2] = shape[2], shape[axis]
    elif labels[:2] == ['spatial', 'spatial'] and labels[2:3] != ['spatial']:
        labels.insert(2, 'slice')
        shape.insert(2, 1)
    return labels, shape


def image_shape(dataset):
    """The shape one reconstruction assembles to, without reading its data."""
    labels = axis_labels(dataset)
    return normalized_axes(labels, tuple(dataset.shape_final)[:len(labels)])[1]


def collapse_scale(factors):
    """One value when every frame shares it, else the per-frame array.

    NIfTI's ``scl_slope``/``scl_inter`` are scalars, so a uniform factor lets
    the image stay in its stored word type instead of widening to float.
    """
    values = np.atleast_1d(factors)
    return values[0].item() if is_all_element_same(values.tolist()) else values


class BaseHelper:
    def __init__(self):
        self.warns = []

    def _warn(self, message):
        warnings.warn(message, UserWarning)
        self.warns.append(message)

    def get(self, attr):
        return getattr(self, attr) if hasattr(self, attr) else None
