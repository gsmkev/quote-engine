import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class CatalogItem(BaseModel):
    sku: str
    description: str
    aliases: list[str]


class Catalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: dict[str, CatalogItem]

    @classmethod
    def from_json(cls, path: str | Path) -> "Catalog":
        rows = json.loads(Path(path).read_text())
        return cls(items={r["sku"]: CatalogItem(**r) for r in rows})

    @property
    def skus(self) -> tuple[str, ...]:
        return tuple(self.items)
