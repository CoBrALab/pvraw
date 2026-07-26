from __future__ import annotations
import warnings
import numpy as np
from brkraw_legacy import config
from nibabel.nifti1 import Nifti1Image
from .header import Header
from brkraw_legacy.lib.errors import UnexpectedError
from brkraw_legacy.lib.utils import get_value
from brkraw_legacy.api.helper import axis_labels
from brkraw_legacy.api.helper.base import collapse_scale, normalized_axes
from brkraw_legacy.api.data import Scan
from xnippet.snippet import PlugInSnippet
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Optional, Union, Literal
    from typing import List
    from numpy.typing import NDArray
    from xnippet.types import XnippetManagerType


class BaseMethods:
    config: XnippetManagerType = config

    def set_scale_mode(self, 
                       scale_mode: Optional[Literal['header', 'apply']] = None):
        self.scale_mode = scale_mode or 'header'
    
    @staticmethod
    def get_dataobj(scanobj:'Scan',
                    reco_id:Optional[int] = None,
                    scale_correction:bool = False):
        data_dict = BaseMethods.get_data_dict(scanobj, reco_id)
        dataobj = data_dict['data_array']
        if scale_correction:
            dataobj = BaseMethods._apply_scale(dataobj, data_dict['data_slope'],
                                               data_dict['data_offset'])
        return dataobj

    @staticmethod
    def _apply_scale(dataobj: NDArray, slope, offset):
        """Bake intensity slope/offset into the data array.

        Scalar factors broadcast trivially. Per-frame factors (one value per
        frame, which the scalar NIfTI scl_slope/scl_inter cannot represent) are
        reshaped onto the trailing frame axes in Fortran order -- the order
        get_dataarray reads the 2dseq buffer in -- matching the BrukerLoader
        scaling. Falls back to leaving the data unscaled (with a warning) if the
        factors do not map onto the frame axes.
        """
        def broadcast(v):
            v = np.asarray(v)
            if v.ndim == 0:
                return v
            # frames occupy the trailing axes whose product equals v.size
            k = dataobj.ndim
            prod = 1
            while k > 0 and prod < v.size:
                k -= 1
                prod *= dataobj.shape[k]
            frame_shape = dataobj.shape[k:]
            if int(np.prod(frame_shape)) != v.size:
                raise ValueError('scale factor size does not map to frame axes')
            return v.reshape(frame_shape, order='F').reshape((1,) * k + tuple(frame_shape))
        try:
            return dataobj * broadcast(slope) + broadcast(offset)
        except ValueError:
            warnings.warn(
                "Scale correction not applied. The 'slope' and 'offset' provided are not in a tested condition. "
                "For further assistance, contact the developer via issue at: https://github.com/gdevenyi/brkraw-legacy.git",
                UserWarning)
            return dataobj
    
    @staticmethod
    def get_affine(scanobj:'Scan', reco_id: Optional[int] = None, 
                   subj_type: Optional[str]=None, 
                   subj_position: Optional[str]=None):
        return BaseMethods.get_affine_dict(scanobj, reco_id, 
                                           subj_type, subj_position)['affine']
    
    @staticmethod
    def _ensure_image_data(scanobj: 'Scan', reco_id: Optional[int] = None):
        """Reject non-image (spectroscopic/temporal) scans before the image pipeline.

        A frame is a conventional image only when every VisuCoreDimDesc entry is
        'spatial'. Spectroscopy (PRESS/STEAM/ISIS/NSPECT/CSI/...) and temporal
        data cannot become a NIfTI, and forcing them through the pipeline crashes
        with opaque errors. VisuCoreDimDesc is read straight from visu_pars
        because the full analysis itself fails on these scans; raising a clear,
        catchable error matches the BrukerLoader path.
        """
        dim_desc = get_value(scanobj.get_visu_pars(reco_id), 'VisuCoreDimDesc')
        non_spatial = [str(d) for d in np.atleast_1d(dim_desc) if str(d) != 'spatial']
        if non_spatial:
            raise UnexpectedError(
                'non-image data (contains {}); skipped for NIfTI conversion'
                ''.format(', '.join(sorted(set(non_spatial)))))

    @staticmethod
    def get_data_dict(scanobj: 'Scan',
                      reco_id: Optional[int] = None):
        """The image array of one reconstruction, with one named axis per Frame Group.

        `brukerapi` returns the array already assembled -- frames folded into
        their Frame Groups, in the word type the scanner wrote, in the order its
        affine describes -- and names every axis (ADR 0002). All that is left is
        to put the slice axis where the affine expects it.
        """
        BaseMethods._ensure_image_data(scanobj, reco_id)
        dataset = scanobj.get_dataset(reco_id, with_data=True)
        labels = axis_labels(dataset)
        dataarray = dataset.data
        if dataarray.ndim > len(labels):
            # the trailing size-1 placeholder axis of a frame-group-less reco
            dataarray = dataarray.reshape(dataarray.shape[:len(labels)])
        dataarray = BaseMethods._normalize_slice_axis(dataarray, labels)
        return {
            'data_array': dataarray,
            'data_slope': collapse_scale(dataset.slope),
            'data_offset': collapse_scale(dataset.offset),
            'axis_labels': labels
        }

    @staticmethod
    def _normalize_slice_axis(dataarray: NDArray, axis_labels: list):
        """Move the array onto the axis order ``normalized_axes`` describes:
        the slice axis at position k (2), inserted when the acquisition stores
        none. Mutates ``axis_labels`` in place and returns the array."""
        normalized, _ = normalized_axes(axis_labels, dataarray.shape)
        if len(normalized) > len(axis_labels):
            dataarray = np.expand_dims(dataarray, 2)
        elif normalized != axis_labels:
            dataarray = np.swapaxes(dataarray, axis_labels.index('slice'), 2)
        axis_labels[:] = normalized
        return dataarray

    @staticmethod
    def get_affine_dict(scanobj: 'Scan', reco_id: Optional[int] = None,
                        subj_type: Optional[str] = None, 
                        subj_position: Optional[str] = None):
        # Geometry is only meaningful for image data; rejecting here (rather
        # than when the scan is first addressed) keeps parameter reads working
        # for a spectroscopic scan, which a study listing still has to describe.
        BaseMethods._ensure_image_data(scanobj, reco_id)
        affine_analyzer = scanobj.get_affine_analyzer(reco_id)
        subj_type = subj_type or affine_analyzer.subj_type
        subj_position = subj_position or affine_analyzer.subj_position
        affine = affine_analyzer.get_affine(subj_type, subj_position)
        return {
            "num_slicepacks": len(affine) if isinstance(affine, list) else 1,
            "affine": affine,
            "subj_type": subj_type,
            "subj_position": subj_position
        }
        
    @staticmethod
    def update_nifti1header(scanobj: 'Scan', 
                            nifti1image: 'Nifti1Image', 
                            reco_id: Optional[int] = None, 
                            scale_mode: Optional[Literal['header', 'apply']] = None):
        if reco_id:
            scanobj.set_scaninfo(reco_id)
        scale_mode = scale_mode or 'header'
        return Header(scaninfo=scanobj.info, nifti1image=nifti1image, scale_mode=scale_mode).get()

    @staticmethod
    def get_nifti1image(scanobj: 'Scan', 
                        reco_id: Optional[int] = None, 
                        scale_mode: Optional[Literal['header', 'apply']] = None,
                        subj_type: Optional[str] = None, 
                        subj_position: Optional[str] = None,
                        plugin: Optional[Union['PlugInSnippet', str]] = None, 
                        plugin_kws: Optional[dict] = None) -> Optional[Union['Nifti1Image', List['Nifti1Image']]]:
        if plugin:
            if nifti1image := BaseMethods._bypass_method_via_plugin(scanobj=scanobj,
                                                                    subj_type=subj_type, subj_position=subj_position,
                                                                    plugin=plugin, plugin_kws=plugin_kws):
                return nifti1image
            else:
                return None
        else:
            scale_mode = scale_mode or 'header'
            # Fetch the data dict once (a 2dseq load is not cached) so we get the
            # axis labels alongside the array; the labels drive multi-volume
            # grouping in _assemble_nifti1image.
            data_dict = BaseMethods.get_data_dict(scanobj, reco_id)
            dataobj = data_dict['data_array']
            slope, offset = data_dict['data_slope'], data_dict['data_offset']
            # Bake scaling into the data when asked ('apply') or when the factors
            # are per-frame arrays a scalar NIfTI header cannot hold; scalar
            # 'header' scaling is left for update_nifti1header to write. 'none'
            # writes the stored values with no scaling at all.
            header_scale_mode = scale_mode
            if scale_mode != 'none' and (scale_mode == 'apply' or np.ndim(slope) or np.ndim(offset)):
                dataobj = BaseMethods._apply_scale(dataobj, slope, offset)
                header_scale_mode = 'apply'
            affine = BaseMethods.get_affine(scanobj=scanobj,
                                            reco_id=reco_id,
                                            subj_type=subj_type,
                                            subj_position=subj_position)
            return BaseMethods._assemble_nifti1image(scanobj, dataobj, affine, header_scale_mode,
                                                     axis_labels=data_dict['axis_labels'])
        
    @staticmethod
    def _bypass_method_via_plugin(scanobj: 'Scan', 
                                  subj_type: Optional[str] = None, 
                                  subj_position: Optional[str] = None,
                                  plugin: Optional[Union['PlugInSnippet', str]] = None, 
                                  plugin_kws: Optional[dict] = None) -> Optional[Nifti1Image]:
        if isinstance(plugin, str):
            plugin = BaseMethods._get_plugin_snippets_by_name(plugin)
        if isinstance(plugin, PlugInSnippet) and 'brkraw' in plugin._manifest['package']:  # TODO: need to have better tool to check version compatibility as well.
            print(f'++ Installed PlugIn: {plugin}')
            with plugin.run(pvobj=scanobj.pvobj, **plugin_kws) as p:
                nifti1image = p.get_nifti1image(subj_type=subj_type, subj_position=subj_position)
            return nifti1image
        else:
            warnings.warn("Failed. Given plugin not available, "
                          "please install local plugin or use from available on "
                          f"remote repository. -> {[p.name for p in config.avail]}",
                          UserWarning)
            return None
    
    @staticmethod
    def _get_plugin_snippets_by_name(plugin: str):
        fetcher = config._fetcher
        if not fetcher.is_cache:
            plugin = BaseMethods._filter_snippets_by_name(plugin, fetcher.local)
        if fetcher.is_cache or not isinstance(plugin, PlugInSnippet):
            plugin = BaseMethods._filter_snippets_by_name(plugin, fetcher.remote)
        return plugin
    
    @staticmethod
    def _filter_snippets_by_name(name:str, snippets: list):
        if filtered := [s for s in snippets if s.name == name]:
            return filtered[0]
        else:
            return name
            
    @staticmethod
    def _warn_if_complex(axis_labels):
        """Warn that COMPLEX_IMAGE data is not split into BIDS part- entities.

        A COMPLEX_IMAGE reconstruction stores all real frames then all imaginary
        frames in one 2dseq (FILE_FORMAT.md 3.4), which becomes a single
        multi-volume NIfTI here. Auto-splitting into part-real/part-imag is not
        done -- the real/imag volume order cannot be validated against the
        available sample data, and a wrong split is worse than the (non
        data-losing) stacked volume. The BIDS-correct route is separate
        real/imaginary/phase/magnitude reconstructions with the 'part' datasheet
        column.
        """
        if axis_labels and 'complex' in axis_labels:
            warnings.warn(
                "Complex (real+imaginary) reconstruction written as one "
                "multi-volume image (real volume(s) first, then imaginary). BIDS "
                "'part-real'/'part-imag' splitting is not automated; use separate "
                "real/imaginary/phase/magnitude reconstructions and set the 'part' "
                "column in the datasheet for part-labelled outputs.", UserWarning)

    @staticmethod
    def _assemble_nifti1image(scanobj: 'Scan',
                              dataobj: NDArray,
                              affine: NDArray,
                              scale_mode: Optional[Literal['header', 'apply']] = None,
                              axis_labels: Optional[list] = None):
        BaseMethods._warn_if_complex(axis_labels)
        echo_axis = axis_labels.index('echo') if (axis_labels and 'echo' in axis_labels) else None
        if not isinstance(dataobj, list) and echo_axis is not None and dataobj.shape[echo_axis] > 1:
            # BIDS emits one file per echo, so split the echo axis into separate
            # images. A single-echo FG_ECHO group is not multi-echo data and is
            # left as one volume. Other non-spatial axes (diffusion directions,
            # fMRI cycles, movie/IR frames) collapse into a single 4D image below.
            dataobj = [np.take(dataobj, e, axis=echo_axis)
                       for e in range(dataobj.shape[echo_axis])]
        if isinstance(dataobj, list):
            # one image per echo; collapse any remaining frame axes to 4D
            dataobj = [BaseMethods._flatten_frames(d) for d in dataobj]
            niis = BaseMethods._assemble_msme(dataobj, affine)
            return [BaseMethods.update_nifti1header(nifti1image=nii,
                                                    scanobj=scanobj,
                                                    scale_mode=scale_mode) for nii in niis]
        if isinstance(affine, list):
            # multi-slicepacks: one image per package, the data sliced per
            # package (packages may differ in slice count) so no slices are
            # dropped -- matching the BrukerLoader path.
            counts = scanobj.info.slicepack['num_slices_each_pack']
            niis = BaseMethods._assemble_ms(dataobj, affine, counts)
            return [BaseMethods.update_nifti1header(nifti1image=nii,
                                                    scanobj=scanobj,
                                                    scale_mode=scale_mode) for nii in niis]
        # single image: collapse any frame axes (movie/IR/cycle/diffusion) to 4D
        dataobj = BaseMethods._flatten_frames(dataobj)
        nii = Nifti1Image(dataobj=dataobj, affine=affine)
        return BaseMethods.update_nifti1header(nifti1image=nii,
                                               scanobj=scanobj,
                                               scale_mode=scale_mode)

    @staticmethod
    def _flatten_frames(dataobj: NDArray):
        """Collapse any axes beyond [x, y, slice] into one trailing 4D axis, so
        multi-frame data (movie/IR/cycle/diffusion) becomes a single 4D image
        rather than a >4D array. Echo is split into separate images first."""
        if dataobj.ndim <= 3:
            return dataobj
        x, y, z = dataobj.shape[:3]
        return dataobj.reshape(x, y, z, -1, order='F')

    @staticmethod
    def _assemble_msme(dataobj: NDArray, affine: NDArray):
        affine = affine if isinstance(affine, list) else [affine for _ in range(len(dataobj))]
        return [Nifti1Image(dataobj=dobj, affine=affine[i]) for i, dobj in enumerate(dataobj)]

    @staticmethod
    def _assemble_ms(dataobj: NDArray, affine: NDArray, num_slices_each_pack: list):
        """One image per slice package, sliced from the data with a cumulative
        offset so packages of differing size (e.g. a 5/3/5 scout) keep all their
        slices, rather than taking a single slice per affine."""
        niis = []
        for i, aff in enumerate(affine):
            start = sum(num_slices_each_pack[:i])
            end = start + num_slices_each_pack[i]
            niis.append(Nifti1Image(dataobj=dataobj[:, :, start:end, ...], affine=aff))
        return niis
    
    def list_plugin(self):
        avail_dict = self.config.avail('plugin')
        return {'local': [s for s in avail_dict['local'] if s.type == 'tonifti'],
                'remote': [s for s in avail_dict['remote'] if s.type == 'tonifti']}