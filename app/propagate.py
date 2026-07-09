"""The propagation engine. Deterministic BFS over the link graph. No model, ever.

Implements knowledge/09 exactly:
 direct fragility -> severed roads -> settlement reachability (ISOLATED/REROUTED)
 -> facility SERVICE_AT_RISK, with a why-chain on every impact (invariant 2).

Correctness properties this file must hold (each has a test):
  * Invariant 1 - same inputs, same impacts AND same why-chains. All traversal
    iterates SORTED containers; never a set (str hashes are randomised per
    process, so set order is not stable across runs).
  * Invariant 2 - a settlement's why-chain names the crossing that actually
    blocks THAT settlement's baseline route, not an arbitrary severed road.
  * A severed road is untraversable, including as a path's first or last hop.
    Otherwise a village whose own access road is severed can read "reachable".
"""
import itertools
import json
from collections import defaultdict, deque

from . import db
from .ontology import (BLOCKING_BRIDGE_STATES, FLOODPLAIN_STATE,
                       bridge_state_explained, worse)


def _graph():
    objs = {o["id"]: o for o in db.objects()}
    lks = db.links()
    by_type = {}
    for l in lks:
        by_type.setdefault(l["type"], []).append((l["src"], l["dst"]))
    for t in by_type:                      # determinism (invariant 1)
        by_type[t].sort()
    return objs, by_type


def _road_adj(by_type, removed=(), cut_pairs=()):
    """Adjacency over traversable roads.

    Two distinct effects of a blocked crossing (D-034):
      * `cut_pairs` - the crossing EDGE between the roads either side of it is
        removed. The roads themselves stay traversable: a bridge failing does
        not stop you driving along its approach road to a school on your own bank.
      * `removed` - roads we cannot break locally (a crossing sitting mid-way
        through a single road with no second carrier) are dropped entirely. That
        over-states the break, which is the safe direction.
    """
    removed, cut = set(removed), set(cut_pairs)
    adj = {}
    for a, b in by_type.get("connects", []):
        if a in removed or b in removed:
            continue
        if tuple(sorted((a, b))) in cut:
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return adj


def _hops(adj, starts, goals):
    """BFS shortest hop-count from any start road to any goal road.

    Returns (hops, path) or (None, []). Iterates sorted containers so the path -
    and therefore the why-chain - is identical on every run (invariant 1).
    Callers must pass starts/goals already filtered of severed roads.
    """
    starts = sorted(set(starts))
    goals = set(goals)
    if not starts or not goals:
        return None, []
    seen = {s: [s] for s in starts}
    q = deque(starts)
    while q:
        cur = q.popleft()
        if cur in goals:
            return len(seen[cur]), seen[cur]
        for nxt in sorted(adj.get(cur, ())):
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
        # NOTE: no "bridge" default. An unclassified crossing must NOT be scored
        # as the least-fragile structure; ontology.resolve_structure applies the
        # conservative most-fragile assumption instead (D-027).
        st, eff, assumed = bridge_state_explained(
            objs[bid]["props"].get("structure"), kind, sev)
        if st != "OK":
            chain = [f"hazard:{kind}/{sev}", reach_id, bid]
            if assumed:
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

    # 2) severed roads (roads carrying blocked bridges). A road carrying a
    #    blocked crossing is SEVERED (impact state). How that break is applied to
    #    the network depends on how many roads the crossing joins (D-034):
    #      >= 2 carriers -> cut the crossing edge between them, roads survive
    #       1 carrier    -> the break is mid-road and cannot be localised; drop it
    carriers_of = defaultdict(list)
    for road, bid in by_type.get("carries", []):
        carriers_of[bid].append(road)

    severed, removed_roads, cut_pairs = {}, set(), set()
    for bid in sorted(blocked_bridges):
        roads = sorted(set(carriers_of.get(bid, [])))
        for road in roads:
            severed[road] = bid
            hit(road, "SEVERED", [f"hazard:{kind}/{sev}", reach_id, bid, road])
        if len(roads) >= 2:
            for a, b in itertools.combinations(roads, 2):
                cut_pairs.add(tuple(sorted((a, b))))
        elif len(roads) == 1:
            removed_roads.add(roads[0])

    # 3) settlement reachability to the facilities that serve them
    adj_before = _road_adj(by_type)
    adj_after = _road_adj(by_type, removed_roads, cut_pairs)
    access = {}
    for s, r in by_type.get("access_via", []):
        access.setdefault(s, []).append(r)
    serves = {}
    for fac, settlement in by_type.get("serves", []):
        serves.setdefault(settlement, []).append(fac)

    # 09 step 4 is PER FACILITY: "test whether any path ... reaches EACH facility
    # that serves it. No path at all -> ISOLATED." Pooling facilities and taking
    # the minimum hop count silently hides the loss of one of them - a village
    # that loses its clinic but keeps its local school would report nothing.
    # That is an under-warning (D-032).
    facility_lost = {}
    blocking_by_fac = {}
    for st_id in sorted(serves):
        facs = sorted(serves[st_id])
        entries = access.get(st_id, [])
        # a road dropped from the network cannot be a start or a goal - not even
        # a zero-hop one. (A road that is merely cut at its crossing survives.)
        entries_after = [r for r in entries if r not in removed_roads]

        for fac in facs:
            goals = access.get(fac, [])
            goals_after = [g for g in goals if g not in removed_roads]
            hb, pb = _hops(adj_before, entries, goals)
            ha, pa = _hops(adj_after, entries_after, goals_after)

            if hb is None:
                # never had a road route to this facility: a data/coverage gap,
                # not an impact of this hazard. It must NOT make the facility
                # SERVICE_AT_RISK either (D-033).
                continue
            if ha is not None and ha <= hb:
                continue                      # unaffected

            # invariant 2: name the crossing that actually blocks THIS
            # settlement's route to THIS facility - the first severed road along
            # its baseline path, and the bridge that severed that road.
            blocking_road = next((r for r in pb if r in severed), None)
            if blocking_road is None:
                blocking_road = next((r for r in entries if r in severed), None)
            blocking_bridge = severed.get(blocking_road) if blocking_road else None

            chain = [f"hazard:{kind}/{sev}", reach_id]
            if blocking_bridge:
                chain.append(blocking_bridge)
            if blocking_road:
                chain.append(blocking_road)
            chain += [st_id, fac]

            if ha is None:
                hit(st_id, "ISOLATED", chain)
                facility_lost.setdefault(fac, []).append(st_id)
                if blocking_bridge:
                    blocking_by_fac.setdefault(fac, set()).add(blocking_bridge)
            else:                              # ha > hb: a longer way round
                hit(st_id, "REROUTED",
                    chain + ["alternate_via:" + ">".join(pa)])

    # 4) facilities whose communities lost access. Only settlements that HAD
    #    baseline access and lost it count (D-033); the chain names the crossings.
    for fac in sorted(facility_lost):
        lost = sorted(set(facility_lost[fac]))
        if not lost:
            continue
        bridges = sorted(blocking_by_fac.get(fac, ()))
        hit(fac, "SERVICE_AT_RISK",
            [f"hazard:{kind}/{sev}", reach_id] + bridges + lost + [fac])

    # persist
    with db.conn() as c:
        for oid in sorted(impacts):
            state, chain = impacts[oid]
            c.execute("INSERT INTO impacts (hazard_id, object_id, state, "
                      "why_chain_json, created_utc) VALUES (?,?,?,?,?)",
                      (hazard_id, oid, state, json.dumps(chain), db.now()))
    return {"hazard_id": hazard_id, "impacts": len(impacts)}
