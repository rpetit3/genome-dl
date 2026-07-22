"""Custom exceptions for genome-dl."""


class GenomeDLError(Exception):
    """Base exception for genome-dl."""

    pass


class ValidationError(GenomeDLError):
    """Invalid accession or input."""

    pass


class ApiError(GenomeDLError):
    """Error from the NCBI Datasets REST API."""

    def __init__(self, message: str, status_code: int = None):
        self.status_code = status_code
        super().__init__(message)


class TaxonError(GenomeDLError):
    """The requested taxon is not a recognized NCBI Taxonomy name."""

    pass


class EmptyResultError(GenomeDLError):
    """A valid taxon returned no assemblies for the requested filters."""

    pass


class DownloadError(GenomeDLError):
    """Error while downloading assembly files."""

    def __init__(self, message: str, accession: str = None):
        self.accession = accession
        super().__init__(message)


class AccessionNotFoundError(GenomeDLError):
    """All requested accessions failed to resolve or download."""

    def __init__(self, message: str, failed: list[str] = None):
        self.failed = failed or []
        super().__init__(message)


class PartialDownloadError(GenomeDLError):
    """Some assemblies were downloaded but others failed."""

    def __init__(
        self, message: str, failed: list[str] = None, successful: list[str] = None
    ):
        self.failed = failed or []
        self.successful = successful or []
        super().__init__(message)
