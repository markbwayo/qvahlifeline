"""Ontology registry v0.1 - mirrors knowledge/09_ontology_spec.md. Code follows the
spec, never the reverse. Deterministic: no model touches anything in this file."""

ONTOLOGY_VERSION = ("LIFELINE ontology v0.4 (2026-07) - hazard-kind registry, playbook "
                    "contract, broadcast + CAP registry")

OBJECT_TYPES = ["river_reach", "bridge", "road_segment", "settlement", "clinic",
                "school", "water_point"]

LINK_TYPES = ["crosses", "carries", "connects", "access_via", "serves",
              "on_floodplain"]

SEVERITIES = ["watch", "alert", "emergency"]

# The hazard kinds the ontology knows (09, object type `hazard`). The playbook
# loader validates against this list: a typo'd hazard_kind in data/playbook.csv
# would otherwise match nothing and fire no action - a silent no-action, which is
# the action-layer form of a false all-clear.
HAZARD_KINDS = ["riverine_flood", "extreme_rain"]

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


# --------------------------------------------------------------- broadcast rules
# Which impacts a community is BROADCAST about. A versioned rule, not a CSV
# accident: adding a state here is a decision about what a village is told, and
# it belongs in 09 before it belongs in a template file.
#
# An officer does not need a message; he needs a task, and the playbook already
# gives him one with an owner and a lead time. Restating verbatim committee text
# as prose would mean paraphrasing it, which the playbook contract forbids.
BROADCAST_STATES = {
    ("settlement", "ISOLATED"),
    ("bridge", "IMPASSABLE"),
    ("bridge", "LIKELY_IMPASSABLE"),
}

# Templates may only use these slots, per object type. The whitelist is the
# enforcement point for D-051: `lead_time` is the playbook's completion deadline
# for an owner, not the hour the water arrives, and `trigger_detail` carries
# numbers no broadcast should claim. Neither is a slot, so neither can be typed
# into a template by accident.
MESSAGE_SLOTS = {
    "settlement": {"settlement", "facility", "facility_type", "facilities",
                   "crossing", "hazard", "severity"},
    "bridge": {"crossing", "structure", "hazard", "severity"},
}

# Languages a template file may declare. Swahili is drafted at the AI edge and
# marked DRAFT; it is never authored here, and English is what the system
# degrades to when the edge is unavailable.
TEMPLATE_LANGS = ["en", "lum"]

# ------------------------------------------------------------------ CAP mapping
# Common Alerting Protocol 1.2. Aligning these fields is what lets a national
# system ingest a LIFELINE warning (04.E). Every value below is derived from
# something the engine computed; nothing is invented to fill a field.
CAP_SEVERITY = {"watch": "Moderate", "alert": "Severe", "emergency": "Extreme"}

# CAP urgency answers "how long until responsive action should be taken" - a
# TIME. LIFELINE does not model arrival time (D-051): the trigger is a discharge
# return period, and lead_time_hrs is an owner's deadline. CAP 1.2 provides
# "Unknown" for exactly this case. We use it rather than derive a time we never
# computed. Saying Unknown honestly beats saying Immediate confidently.
CAP_URGENCY = "Unknown"

# CAP certainty, straight out of the why-chain. A crossing whose structure nobody
# classified was scored under the D-027 assumption, and its chain says so. That
# admission becomes machine-readable confidence: the warning still fires, at a
# lower certainty, and a national system can see why.
CAP_CERTAINTY_ASSUMED = "Possible"   # blocking crossing unclassified (assumed ford)
CAP_CERTAINTY_KNOWN = "Likely"       # blocking crossing has an engineer-known structure
