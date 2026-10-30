"""Keys the loader and the fixtures must compute the same way.

`slice_key` names what a batch covers (09 section 2.6: location, business-date range, report):
applying a batch supersedes the applied batch with the same key, so every writer of
import_batch (the batch loader, the fixture seed) must build it with this function.
`normalize_name` is menu_item.normalized_name, which the loader matches report names on.
"""

from __future__ import annotations

import unicodedata
from uuid import UUID

from mermia_contracts.batch import Period


def slice_key(location_id: UUID | str, parser: str, period: Period) -> str:
    """'<location>:<parser without version>:<from>:<to>', e.g. '...:sr.productos_vendidos:...'."""
    report = parser.split("@", 1)[0]
    return f"{location_id}:{report}:{period.from_.isoformat()}:{period.to.isoformat()}"


def normalize_name(name: str) -> str:
    """Lower case, no accents, no parentheses, single spaces: 'Tacos al pastor (orden de 3)' ->
    'tacos al pastor orden de 3'."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().replace("(", " ").replace(")", " ").split())
