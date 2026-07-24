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
    ``VisuCoreDimDesc``, then one per Frame Group (``<FG_ECHO>`` and so on).
    Strip the JCAMP-DX quoting and the ``FG_`` prefix so the rest of the code
    reads ``echo``, ``slice``, ``diffusion``.

    Two axes need naming rather than renaming. A reconstruction with no frame
    groups carries a trailing size-1 ``frame`` placeholder, which is dropped --
    a 3D volume is ``(x, y, z)``, not ``(x, y, z, 1)``. A single-slice 2D
    acquisition carries an inserted size-1 third axis, which *is* the slice
    axis the affine's third column addresses, so it is named as one.
    """
    labels = []
    for name in dataset.dim_type:
        name = str(name).strip('<>')
        labels.append(name[3:].lower() if name.upper().startswith('FG_') else name.lower())
    if labels[-1:] == ['frame']:
        labels = labels[:-1]
    if getattr(dataset, 'is_single_slice', False) and len(labels) > 2:
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
    first = dataset.encoded_dim + (1 if getattr(dataset, 'is_single_slice', False) else 0)
    return list(zip(labels[first:], sizes[first:]))


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
