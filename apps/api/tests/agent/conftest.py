from uuid import UUID

import pytest

CENTRO = UUID("705e8e51-376b-5785-adbb-405eff4e2a22")
POLANCO = UUID("fdda5e3b-6bcd-5c48-a6de-f524be37463e")


@pytest.fixture
def el_guero() -> dict[UUID, str]:
    """The two El Güero locations, as the eval system prompt names them."""
    return {CENTRO: "Centro", POLANCO: "Polanco"}
