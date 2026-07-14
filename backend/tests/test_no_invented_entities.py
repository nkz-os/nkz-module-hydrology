"""Anti-regression: the module must NEVER publish invented NGSI-LD entity types.

Allowed SDM types for writes: AgriParcelRecord, AgriParcelZone.
Design entities use the spec §6.1 NKZ own types nkz:WaterStorage /
nkz:OpenChannelFlow (frozen, hosted @context) — those are sanctioned.
Invented legacy types that were removed (must stay gone):
  nkz:HydrologyDesign, TWI_H3, WaterBalanceAssessment, WaterBalanceObservation.
"""
import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

FORBIDDEN_TYPES = {
    "HydrologyDesign",
    "nkz:HydrologyDesign",
    "TWI_H3",
    "WaterBalanceAssessment",
    "WaterBalanceObservation",
}


def _python_sources():
    for p in APP_DIR.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def test_no_invented_entity_types_in_source():
    offenders = []
    for src in _python_sources():
        text = src.read_text(encoding="utf-8")
        for bad in FORBIDDEN_TYPES:
            # match "type": "..." or 'type': '...' or "type" key constructions
            for m in re.finditer(r'["\']type["\']\s*:\s*["\']([^"\']+)["\']', text):
                if m.group(1) in FORBIDDEN_TYPES:
                    offenders.append(f"{src.relative_to(APP_DIR.parent)}: {m.group(0)}")
    assert not offenders, "Invented entity types still referenced:\n" + "\n".join(offenders)
