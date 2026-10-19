"""Why a file could not be turned into a NormalizedBatch.

Every error carries a Spanish message for the manager (03 B.5: "No reconocí este reporte; necesito
el reporte X") and a stable code for logs and tests. Parsers raise these and nothing else for bad
input, so a wrong file never surfaces as a crash.
"""

from __future__ import annotations


class ReportError(Exception):
    code = "report_error"

    def __init__(self, message_es: str, detail: str = "") -> None:
        super().__init__(detail or message_es)
        self.message_es = message_es
        self.detail = detail


class UnreadableFile(ReportError):
    """Not a file we can open (not an .xlsx, corrupt, password-protected)."""

    code = "unreadable_file"


class UnknownReport(ReportError):
    """A readable file that matches no registered parser."""

    code = "unknown_report"


class MalformedReport(ReportError):
    """The right report, but its rows do not add up or a value is not what the format says."""

    code = "malformed_report"
