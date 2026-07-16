from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.domain.product import ProductInfo


class ApplicationDirectories(Protocol):
    @property
    def data_dir(self) -> Path: ...

    @property
    def cache_dir(self) -> Path: ...

    def ensure(self) -> None: ...


@dataclass(frozen=True, slots=True)
class StartupSnapshot:
    product: ProductInfo
    data_dir: Path
    cache_dir: Path


class BootstrapApplication:
    def __init__(self, product: ProductInfo, directories: ApplicationDirectories) -> None:
        self._product = product
        self._directories = directories

    def execute(self) -> StartupSnapshot:
        self._directories.ensure()
        return StartupSnapshot(
            product=self._product,
            data_dir=self._directories.data_dir,
            cache_dir=self._directories.cache_dir,
        )
