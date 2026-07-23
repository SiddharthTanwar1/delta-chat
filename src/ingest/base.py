"""FormatAdapter: the one interface every ingestion format plugs in behind.
Add a 4th format by writing a class with `sniff` + `ingest` and registering
it -- nothing in delta/, chat/, or eval/ needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.canonical.model import Document


class FormatAdapter(ABC):
    format_name: str

    @abstractmethod
    def sniff(self, path: Path) -> bool:
        """Cheap, best-effort check: can this adapter likely handle `path`?"""

    @abstractmethod
    def ingest(self, path: Path, pid: str, revision: str = "") -> Document:
        """Parse `path` into the canonical Document representation."""


_REGISTRY: list[FormatAdapter] = []


def register(adapter: FormatAdapter) -> None:
    _REGISTRY.append(adapter)


def detect_and_ingest(path: str | Path, pid: str, revision: str = "") -> Document:
    path = Path(path)
    if not _REGISTRY:
        _bootstrap_registry()
    for adapter in _REGISTRY:
        if adapter.sniff(path):
            return adapter.ingest(path, pid, revision=revision)
    raise ValueError(
        f"No adapter could handle {path} (tried: {[a.format_name for a in _REGISTRY]})"
    )


def _bootstrap_registry() -> None:
    # imported lazily to avoid circular imports at module load time
    from src.ingest.pdf_native import NativePdfAdapter
    from src.ingest.pdf_scanned import ScannedPdfAdapter
    from src.ingest.dwg import DwgAdapter

    # scanned check must run before native (native's sniff would also match
    # a scanned PDF since both have the .pdf extension)
    register(ScannedPdfAdapter())
    register(NativePdfAdapter())
    register(DwgAdapter())
