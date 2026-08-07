"""Derived reconstructions: ParaVision's computed parametric maps and tensor stacks.

A derived reconstruction is not an image, it is a *stack* of them. An ISA fit writes
five volumes -- the fitted signal, the relaxation time, and three quality maps -- and
a DTI reconstruction writes twenty-two. Converting either one whole produces a file
whose fourth dimension means something different in every index, which is why they
used to be dropped instead.

What is machine-readable, and consistent across PV5.1 and PV6:

* ``VisuFGOrderDesc`` names the model, e.g. ``'T2 relaxation: y=A+C*exp(-t/T2)'``
* ``VisuFGElemComment`` names every element, e.g. ``'T2 relaxation time'``

So the map can be found by name rather than by position, and the rest of the stack
kept as what it is -- fit diagnostics with no raw BIDS suffix.
"""
from .utils import get_value

#: Frame groups ParaVision uses for a computed reconstruction rather than an
#: acquired one. ``isa`` is a parameter fit, ``dti`` a tensor reconstruction.
DERIVED_FRAME_GROUPS = ('isa', 'dti')

#: Element comment (lowercased) -> the raw BIDS anat suffix it becomes, and the
#: factor taking Bruker's units to the ones the suffix requires.
#:
#: BIDS is explicit that ``T1map`` and ``T2map`` are "In seconds (s)", while
#: ParaVision fits in milliseconds -- verified on the corpus, where the T1 map peaks
#: at 6600 and the T2 map at 1329. Writing the raw element would be off by 1000.
ISA_MAPS = {
    't1 relaxation time': ('T1map', 1e-3),
    't2 relaxation time': ('T2map', 1e-3),
}


def element_comments(visu_pars):
    """The per-element labels of a frame group, as a list of strings."""
    comments = get_value(visu_pars, 'VisuFGElemComment')
    if comments is None:
        return []
    if isinstance(comments, str):
        return [comments]
    return [str(c) for c in comments]


def is_derived(frame_groups):
    """True when a reconstruction was computed by ParaVision rather than acquired.

    ``frame_groups`` is the ``(name, size)`` sequence from ``get_frame_groups``.
    """
    return any(name in DERIVED_FRAME_GROUPS for name, _ in frame_groups)


def isa_map(visu_pars):
    """``(index, suffix, scale)`` for the parametric map inside an ISA stack.

    ``None`` when this is not an ISA fit, or is one whose fitted quantity has no
    raw BIDS suffix. The index is into the last dimension of the converted image:
    the ISA frame group is the only non-slice frame axis, and the converter moves
    slice to axis 2, so element *k* is ``dataobj[..., k]``.

    Found by label rather than by position on purpose -- the position happens to be
    stable across the corpus, but the label is what actually states the meaning.
    """
    if not _map_is_a_single_volume(visu_pars):
        return None
    for index, comment in enumerate(element_comments(visu_pars)):
        entry = ISA_MAPS.get(comment.strip().lower())
        if entry:
            suffix, scale = entry
            return index, suffix, scale
    return None


def _map_is_a_single_volume(visu_pars):
    """True when the ISA axis is the only thing making volumes.

    A fit can be repeated along another axis -- PV5.1 scan 31 is FG_ISA x FG_ECHO,
    five maps over five echoes -- and then there is no single T1map to extract.
    BIDS has no echo- entity for a parametric map (`echo not in rule
    rules.files.raw.anat.parametric`), and picking one echo silently would discard
    the rest, so the whole stack goes to derivatives instead.

    A slice axis does not count: the converter moves it to k, so it makes voxels
    rather than volumes.
    """
    from .utils import get_value

    desc = get_value(visu_pars, 'VisuFGOrderDesc')
    if desc is None:
        return True
    rows = desc if isinstance(desc[0], (list, tuple)) else [desc]
    extra = [str(r[1]) for r in rows if str(r[1]) not in ('FG_ISA', 'FG_SLICE')]
    return not extra
