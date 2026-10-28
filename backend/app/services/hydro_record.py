"""Shared helpers to read the latest hydrology AgriParcelRecord.

The hydrology record is discriminated from foreign AgriParcelRecord (weather-map)
server-side via the ``nkz:demSource`` existence term and client-side via the
``hydrology-`` id prefix (defense-in-depth).
"""
from __future__ import annotations

from typing import Any

from nkz_platform_sdk import SyncOrionClient

_HYDRO_PREFIX = "urn:ngsi-ld:AgriParcelRecord:hydrology-"


def num_attr(attr: Any) -> float | None:
    """Unwrap a possibly-normalized NGSI-LD scalar attribute to float.

    Orion keyValues may return a plain scalar OR a {type, value}/{@value} dict.
    """
    if isinstance(attr, dict):
        attr = attr.get("value", attr.get("@value"))
    try:
        return float(attr) if attr is not None else None
    except (TypeError, ValueError):
        return None


NKZ_NS = "https://nkz-os.org/ns/"


def nkz_attr(entity: dict, name: str) -> Any:
    """Value of an nkz: term in any form the broker returns it, unwrapped.

    The broker answers with the prefixed name, the name compacted by the
    @context, or the full IRI when the term is outside the context it used.
    """
    for key in (f"nkz:{name}", name, NKZ_NS + name):
        if key in entity:
            value = entity[key]
            if isinstance(value, dict):
                value = value.get("value", value.get("@value"))
            return value
    return None


def latest_hydro_record(orion: SyncOrionClient, parcel_id: str) -> dict:
    """Latest hydrology AgriParcelRecord for the parcel (empty dict if none)."""
    entities = orion.query_entities(
        type="AgriParcelRecord",
        q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}");nkz:demSource',
        options="keyValues",
        limit=100,
    ) or []
    hydro = [e for e in entities if str(e.get("id", "")).startswith(_HYDRO_PREFIX)]
    if not hydro:
        return {}
    hydro.sort(key=lambda e: str(e.get("dateObserved", "")), reverse=True)
    return hydro[0]
