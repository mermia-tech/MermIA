"""Canonical phone numbers and WhatsApp ids, shared by onboarding (MR-30) and the sender lookup.

Mexican mobiles used to be dialled as +52 1 plus 10 digits, and WhatsApp webhooks from Mexican
senders still send `wa_id` as 521 plus 10 digits. The canonical form drops that 1: +52 plus 10
digits. Store and look up only canonical forms:
- app_user.phone_e164 = canonical_phone(...)
- channel_identity.external_id (whatsapp) = wa_id(canonical_phone(...))
- MR-27: look a sender up by canonical_wa_id(webhook wa_id), never by the raw value.
"""

from __future__ import annotations

import re

# The same check as app_user.phone_e164 in the database.
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
SEPARATORS = re.compile(r"[\s\-().]")
MX = "+52"
MX_DIGITS = 10
MX_OLD_MOBILE = "1"


def canonical_phone(value: str) -> str:
    """'+52 1 55 1234 5001' -> '+525512345001'. Raises ValueError for a number that is not E.164."""
    phone = SEPARATORS.sub("", value)
    if not E164.match(phone):
        raise ValueError("phone must be E.164 with the country code, e.g. +52 55 1234 5678")
    if not phone.startswith(MX):
        return phone
    national = phone.removeprefix(MX)
    if len(national) == MX_DIGITS + 1 and national.startswith(MX_OLD_MOBILE):
        national = national[1:]
    if len(national) != MX_DIGITS:
        raise ValueError(f"a Mexican phone has {MX_DIGITS} digits after +52")
    return MX + national


def wa_id(phone: str) -> str:
    """The WhatsApp id stored in channel_identity.external_id: the canonical digits, no '+'."""
    return phone.removeprefix("+")


def canonical_wa_id(external_id: str) -> str:
    """A webhook's wa_id ('5215512345001') in the stored form ('525512345001')."""
    return wa_id(canonical_phone("+" + external_id))
