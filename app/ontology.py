"""Ontology registry v0.1 - mirrors knowledge/09_ontology_spec.md. Code follows the
spec, never the reverse. Deterministic: no model touches anything in this file."""

ONTOLOGY_VERSION = "LIFELINE ontology v0.1 (2026-07)"

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


def bridge_state(structure: str, hazard_kind: str, severity: str) -> str:
    return FRAGILITY.get(("bridge", structure or "bridge", hazard_kind, severity), "OK")
