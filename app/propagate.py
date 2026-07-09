"""The propagation engine. Deterministic BFS over the link graph. No model, ever.

Implements knowledge/09 exactly:
 direct fragility -> severed roads -> settlement reachability (ISOLATED/REROUTED)
 -> facility SERVICE_AT_RISK, with a why-chain on every impact (invariant 2).
"""
import json
from collections import deque

from . import db
from .ontology import (BLOCKING_BRIDGE_STATES, FLOODPLAIN_STATE,
                       bridge_state_explained, worse)


def _graph():
    objs = {o["id"]: o for o in db.objects()}
    lks = db.links()
    by_type = {}
    for l in lks:
        by_type.setdefault(l["type"], []).append((l["src"], l["dst"]))
    return objs, by_type


def _road_adj(by_type, severed):
    adj = {}
    for a, b in by_type.get("connects", []):
        if a in severed or b in severed:
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return adj


def _hops(adj, starts, goals):
    """BFS shortest hop-count from any start road to any goal road; None if no path."""
    starts, goals = set(starts), set(goals)
    if not starts or not goals:
        return None, []
    seen = {s: [s] for s in starts}
    q = deque(starts)
    while q:
        cur = q.popleft()
        if cur in goals:
            return len(seen[cur]), seen[cur]
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen[nxt] = seen[cur] + [nxt]
                q.append(nxt)
    return None, []


def run(hazard_id: int) -> dict:
    """Propagate one active hazard. Idempotent: clears its derived rows first."""
    with db.conn() as c:
        hz = c.execute("SELECT * FROM hazards WHERE id=?", (hazard_id,)).fetchone()
        if not hz or not hz["active"]:
            return {"error": "hazard not found or inactive"}
        db.clear_derived(c, hazard_id)

    objs, by_type = _graph()
    kind, sev, reach_id = hz["kind"], hz["severity"], hz["target_id"]
    impacts = {}   # object_id -> (state, why_chain)

    def hit(oid, state, chain):
        if oid in impacts:
            old_state, old_chain = impacts[oid]
            w = worse(old_state, state)
            impacts[oid] = (w, chain if w == state and w != old_state else old_chain)
        else:
            impacts[oid] = (state, chain)

    # 1) direct: crossings of the flooded reach
    blocked_bridges = {}
    for bid, rid in by_type.get("crosses", []):
        if rid != reach_id:
            continue
        # NOTE: no "bridge" default here. An unclassified crossing must NOT be
        # scored as the least-fragile structure; ontology.resolve_structure
        # applies the conservative most-fragile assumption instead (D-027).
        st, eff, assumed = bridge_state_explained(
            objs[bid]["props"].get("structure"), kind, sev)
        if st != "OK":
            chain = [f"hazard:{kind}/{sev}", reach_id, bid]
            if assumed:
                # invariant 2: the impact explains itself, including the fact
                # that the structure was unknown and assumed.
                chain.append(f"assumed_structure:{eff}(unclassified)")
            hit(bid, st, chain)
        if st in BLOCKING_BRIDGE_STATES:
            blocked_bridges[bid] = st

    # 1b) floodplain exposure
    fp_state = FLOODPLAIN_STATE.get(sev)
    if fp_state:
        for oid, rid in by_type.get("on_floodplain", []):
            if rid == reach_id:
                hit(oid, fp_state, [f"hazard:{kind}/{sev}", reach_id, oid])

    # 2) severed roads (roads carrying blocked bridges)
    severed = {}
    for road, bid in by_type.get("carries", []):
        if bid in blocked_bridges:
            severed[road] = bid
            hit(road, "SEVERED", [f"hazard:{kind}/{sev}", reach_id, bid, road])

    # 3) settlement reachability to the facilities that serve them
    adj_before = _road_adj(by_type, set())
    adj_after = _road_adj(by_type, set(severed))
    access = {}
    for s, r in by_type.get("access_via", []):
        access.setdefault(s, []).append(r)
    serves = {}
    for fac, settlement in by_type.get("serves", []):
        serves.setdefault(settlement, []).append(fac)

    facility_lost = {}
    for st_id, facs in serves.items():
        entries = access.get(st_id, [])
        best_before, best_after, lost_path_bridge = None, None, None
        for fac in facs:
            goals = access.get(fac, [])
            hb, _ = _hops(adj_before, entries, goals)
            ha, _ = _hops(adj_after, entries, goals)
            if hb is not None:
                best_before = hb if best_before is None else min(best_before, hb)
            if ha is not None:
                best_after = ha if best_after is None else min(best_after, ha)
            if hb is not None and ha is None:
                facility_lost.setdefault(fac, []).append(st_id)
        if best_before is None:
            continue  # settlement had no baseline access; data gap, not an impact
        sev_road = next(iter(severed), None)
        via = [f"hazard:{kind}/{sev}", reach_id,
               severed.get(sev_road, ""), sev_road or "", st_id]
        via = [v for v in via if v]
        if best_after is None:
            hit(st_id, "ISOLATED", via)
            for fac in facs:
                facility_lost.setdefault(fac, [])
                if st_id not in facility_lost[fac]:
                    facility_lost[fac].append(st_id)
        elif best_after > best_before:
            hit(st_id, "REROUTED", via)

    # 4) facilities whose communities lost access
    for fac, lost in facility_lost.items():
        if lost:
            hit(fac, "SERVICE_AT_RISK",
                [f"hazard:{kind}/{sev}", reach_id] + lost + [fac])

    # persist
    with db.conn() as c:
        for oid, (state, chain) in impacts.items():
            c.execute("INSERT INTO impacts (hazard_id, object_id, state, "
                      "why_chain_json, created_utc) VALUES (?,?,?,?,?)",
                      (hazard_id, oid, state, json.dumps(chain), db.now()))
    return {"hazard_id": hazard_id, "impacts": len(impacts)}
