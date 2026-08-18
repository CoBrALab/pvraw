from __future__ import annotations

from typing import TYPE_CHECKING

from pvraw.lib.utils import get_value

from .base import BaseHelper

if TYPE_CHECKING:
    from ..analyzer import ScanInfoAnalyzer


class Protocol(BaseHelper):
    """Acquisition protocol description, read from the scan's ``acqp``.

    Dependencies:
        acqp
    """
    def __init__(self, analobj: ScanInfoAnalyzer):
        super().__init__()

        acqp = analobj.acqp
        if not acqp:
            self._warn("Failed to fetch all Protocol information because the 'acqp' file is missing from 'analobj'.")
        def value(key):
            return get_value(acqp, key)

        self.sw_version = str(value('ACQ_sw_version'))
        self.operator = value('ACQ_operator')
        self.pulse_program = value('PULPROG')
        self.nucleus = value('NUCLEUS')
        self.protocol_name = value('ACQ_protocol_name') or value('ACQ_scan_name')
        self.scan_method = value('ACQ_method')
        self.subject_pos = value('ACQ_patient_pos')
        self.institution = value('ACQ_institution')
        self.device = value('ACQ_station')

    def get_info(self):
        return {
            'sw_version': self.sw_version,
            'operator': self.operator,
            'institution': self.institution,
            'device': self.device,
            'nucleus': self.nucleus,
            'subject_pos': self.subject_pos,
            'pulse_program': self.pulse_program,
            'protocol_name': self.protocol_name,
            'scan_method': self.scan_method,
            'warns': self.warns
        }
