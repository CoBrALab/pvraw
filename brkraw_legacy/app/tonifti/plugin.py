from __future__ import annotations

from brkraw_legacy.api.data import Scan

from .base import BaseMethods


class ToNiftiPlugin(Scan, BaseMethods):
    """Base class for handling plugin operations, integrating scanning and basic method functionalities.

    This class initializes plugin operations with options for verbose output and integrates functionalities
    from the Scan and BaseMethods classes.

    Args:
        pvobj: The `brukerapi` Experiment for the scan the plugin operates on.
        verbose (bool): Flag to enable verbose output during operations, defaults to False.
        **kwargs: Additional keyword arguments that are passed to the superclass.

    Attributes:
        verbose (bool): Enables or disables verbose output.
    """
    def __init__(self, pvobj,
                 verbose: bool=False,
                 skip_dependency_check: bool=False,
                 **kwargs):
        super().__init__(pvobj, **kwargs)
        self.verbose: bool = verbose
        self.skip_dependency_check: bool = skip_dependency_check
