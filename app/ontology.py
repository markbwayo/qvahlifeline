"""Ontology registry v0.1 - mirrors knowledge/09_ontology_spec.md. Code follows the
spec, never the reverse. Deterministic: no model touches anything in this file."""

ONTOLOGY_VERSION = "LIFELINE ontology v0.2 (2026-07) - conservative unknown-structure fragility"

OBJECT_TYPES = ["river_reach", "bridge", "road_segment", "settlement", "clinic",
                "school", "water_point"]

LINK_TYPES = ["crosses", "carries", "connects", "access_via", "serves",
              "on_floodplain"]

SEVERITIES = ["watch", "alert", "emergency"]

# State ordering: an object always keeps its WORST state.
STATE_ORDER = ["OK", "AT_RISK", "DEGRADED", "REROUTED", "FLOOD_EXPOSED",
               "LIKELY_IMPASSABLE", "SERVICE_AT_RISK", "SEVERED", "IMPASSABLE",
               "ISOLATED"]


def worse(a: str, b: str) -> str:
    return a if STATE_ORDER.index(a) >= STATE_ORDER.index(b) else b


# Fragility rules v0.1 - engineering heuristics, versioned, committee-tunable.
# (object_type, structure, hazard_kind, severity) -> state
FRAGILITY = {
    ("bridge", "bridge", "riverine_flood", "watch"): "OK",
    ("bridge", "bridge", "riverine_flood", "alert"): "AT_RISK",
    ("bridge", "bridge", "riverine_flood", "emergency"): "LIKELY_IMPASSABLE",
    ("bridge", "culvert", "riverine_flood", "watch"): "AT_RISK",
    ("bridge", "culvert", "riverine_flood", "alert"): "LIKELY_IMPASSABLE",
    ("bridge", "culvert", "riverine_flood", "emergency"): "IMPASSABLE",
    ("bridge", "ford", "riverine_flood", "watch"): "AT_RISK",
    ("bridge", "ford", "riverine_flood", "alert"): "LIKELY_IMPASSABLE",
    ("bridge", "ford", "riverine_flood", "emergency"): "IMPASSABLE",
    ("bridge", "causeway", "riverine_flood", "watch"): "AT_RISK",
    ("bridge", "causeway", "riverine_flood", "alert"): "LIKELY_IMPASSABLE",
    ("bridge", "causeway", "riverine_flood", "emergency"): "IMPASSABLE",
}

FLOODPLAIN_STATE = {"alert": "FLOOD_EXPOSED", "emergency": "FLOOD_EXPOSED"}

# Road is unusable for reachability at these bridge states:
BLOCKING_BRIDGE_STATES = {"LIKELY_IMPASSABLE", "IMPASSABLE"}

# Conservative default for an UNCLASSIFIED crossing (structure is None/unknown -
# e.g. a geometrically synthesised crossing awaiting operator review).
#
# We assume the MOST fragile structure, not the least. Rationale (D-027):
#   - Base rate: an unmapped rural crossing is far more likely a ford, low-level
#     crossing or culvert than an engineered bridge.
#   - Asymmetric cost: a false "crossing may be out" costs an inspection; a false
#     "crossing is fine" leaves a village unwarned. Never fail toward all-clear.
# "ford" is the weakest structure in FRAGILITY (watch->AT_RISK, alert->
# LIKELY_IMPASSABLE, emergency->IMPASSABLE), so unknown structures borrow it.
UNKNOWN_STRUCTURE_ASSUMPTION = "ford"

# Structures the fragility table actually knows. Anything else is "unknown".
KNOWN_STRUCTURES = {"bridge", "culvert", "ford", "causeway"}


def resolve_structure(structure):
    """Return (effective_structure, was_assumed).

    An unknown/missing structure resolves to the most-fragile assumption rather
    than silently returning OK from a table miss. Deterministic; no model.
    """
    s = (structure or "").strip().lower()
    if s in KNOWN_STRUCTURES:
        return s, False
    return UNKNOWN_STRUCTURE_ASSUMPTION, True


def bridge_state(structure: str, hazard_kind: str, severity: str) -> str:
    """Fragility lookup with a conservative unknown-structure fallback.

    NEVER returns OK because of a table miss on structure: an unclassified
    crossing is scored as the most fragile structure (see D-027). A genuine
    (structure, hazard, severity) combination absent from FRAGILITY - e.g. an
    unmodelled hazard kind - still yields OK, which is correct: that hazard
    does not act on this object type.
    """
    eff, _ = resolve_structure(structure)
    return FRAGILITY.get(("bridge", eff, hazard_kind, severity), "OK")


def bridge_state_explained(structure: str, hazard_kind: str, severity: str):
    """As bridge_state, but also reports whether the structure was assumed, so
    the why-chain can say so out loud (invariant 2: impacts explain themselves)."""
    eff, assumed = resolve_structure(structure)
    return FRAGILITY.get(("bridge", eff, hazard_kind, severity), "OK"), eff, assumed
