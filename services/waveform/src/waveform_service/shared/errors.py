"""How the worker classifies a failure (contracts/events/README.md, "Rules for consumers")."""


class ProcessingError(Exception):
    """A failure with a machine-readable code, sent as WaveformProcessingFailed.error_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PermanentError(ProcessingError):
    """Retrying cannot help, e.g. audio ffmpeg cannot decode: give up straight away."""


class TransientError(ProcessingError):
    """Might succeed later, e.g. the S3 object is not there yet: retry, then give up."""
