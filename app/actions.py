"""Playbook -> actions. Data in, rows out. No model, no invented text, ever.

The committee owns `data/playbook.csv` (D-007). This module only *fires* it:
every action row is a verbatim playbook row bound to exactly one impact id.

Invariant 4 (09): no action without a matching impact; no impact state outside
the ontology's declared vocabulary. Both are enforced here at runtime, not only
in the tests, because both failures are silent by nature.

The failure direction that matters (see HANDOFF §3):
  * An invented action is an over-warning - visible, embarrassing, survivable.
  * An impact with NO playbook row fires nothing. The engine says a village is
    ISOLATED and the officer's screen shows no action next to it. That is a
    false all-clear wearing the engine's clothes. So `fire_actions` counts and
    RETURNS every uncovered impact; it never drops one quietly.
"""
import csv
import json
import os
import sys

from . import db
from .ontology import HAZARD_KINDS, OBJECT_TYPES, STATE_ORDER

PLAYBOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "playbook.csv")
PLAYBOOK_VERSION = "playbook v1.0 (2026-07) - riverine_flood, Manafwa pilot"

COLUMNS = ["object_type", "state", "hazard_kind",
           "action_text", "owner_role", "lead_time_hrs"]

# An ISOLATED settlement has, by definition, no remaining road path to that
# facility - the BFS proved it. Action text that tells an officer to drive round
# is a lie the engine has already disproved, and on the Manafwa spine it would
# send him over a second bridge under the same flood (D-038).
FORBIDDEN_IN_ISOLATED = ("alternate route", "alternative route",
                         "detour", "reroute", "re-route", "another route")


class PlaybookError(Exception):
    """The playbook is data, so a bad row is a data error - loud, with a line number."""


class ActionsError(Exception):
    """A structural violation of invariant 4 detected at fire time."""


# --------------------------------------------------------------------------- load

def load_playbook(path=None):
    """Read data/playbook.csv into {(object_type, state, hazard_kind): [row, ...]}.

    Match is an EXACT triple. There are no wildcards (D-043): a `*` row can
    silently shadow a specific one, and "which row won?" must never be a
    question an officer has to ask. Several rows may share a triple - they all
    fire, in a deterministic order.

    Every row is validated against the ontology. A typo'd type/state/kind would
    otherwise match no impact, fire no action, and raise nothing.
    """
    path = path or PLAYBOOK_PATH
    if not os.path.exists(path):
        raise PlaybookError(f"playbook not found: {path}")

    book, seen = {}, set()
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (rd.fieldnames or [])]
        if missing:
            raise PlaybookError(f"playbook missing columns: {missing}")

        for n, raw in enumerate(rd, start=2):     # line 1 is the header
            row = {c: (raw.get(c) or "").strip() for c in COLUMNS}
            if not any(row.values()):
                continue                          # tolerate blank lines

            if row["object_type"] not in OBJECT_TYPES:
                raise PlaybookError(f"line {n}: unknown object_type {row['object_type']!r}")
            if row["state"] not in STATE_ORDER:
                raise PlaybookError(f"line {n}: unknown state {row['state']!r}")
            if row["state"] == "OK":
                raise PlaybookError(f"line {n}: state OK produces no impact, so no action")
            if row["hazard_kind"] not in HAZARD_KINDS:
                raise PlaybookError(f"line {n}: unknown hazard_kind {row['hazard_kind']!r}")
            if not row["action_text"]:
                raise PlaybookError(f"line {n}: empty action_text")
            if not row["owner_role"]:
                raise PlaybookError(f"line {n}: empty owner_role - an action nobody owns "
                                    f"is not an action")
            try:
                lead = int(row["lead_time_hrs"])
            except ValueError:
                raise PlaybookError(f"line {n}: lead_time_hrs {row['lead_time_hrs']!r} "
                                    f"is not an integer")
            if lead < 0:
                raise PlaybookError(f"line {n}: negative lead_time_hrs")
            row["lead_time_hrs"] = lead

            if row["state"] == "ISOLATED":
                low = row["action_text"].lower()
                for bad in FORBIDDEN_IN_ISOLATED:
                    if bad in low:
                        raise PlaybookError(
                            f"line {n}: ISOLATED action offers a road alternate "
                            f"({bad!r}); the engine has proved there is none")

            key = (row["object_type"], row["state"], row["hazard_kind"])
            fingerprint = key + (row["action_text"],)
            if fingerprint in seen:
                raise PlaybookError(f"line {n}: duplicate action for {key}")
            seen.add(fingerprint)
            book.setdefault(key, []).append(row)

    if not book:
        raise PlaybookError(f"playbook is empty: {path}")

    for key in book:                              # determinism (invariant 1)
        book[key].sort(key=lambda r: (r["lead_time_hrs"], r["owner_role"],
                                      r["action_text"]))
    return book


def covered_triples(book=None):
    """The (object_type, state, hazard_kind) triples the playbook answers."""
    return set((book or load_playbook()).keys())


# --------------------------------------------------------------------------- fire

def clear_actions(c, hazard_id):
    c.execute("DELETE FROM actions WHERE impact_id IN "
              "(SELECT id FROM impacts WHERE hazard_id=?)", (hazard_id,))


def fire_actions(hazard_id: int, path=None) -> dict:
    """Fire the playbook against the impacts of one hazard. Idempotent.

    Returns counts plus `uncovered`: impacts for which the playbook has no row.
    An uncovered impact is not an error here - the committee may deliberately
    choose not to act on `bridge AT_RISK` - but it is never invisible.
    """
    book = load_playbook(path)

    with db.conn() as c:
        hz = c.execute("SELECT * FROM hazards WHERE id=?", (hazard_id,)).fetchone()
        if hz is None:
            raise ActionsError(f"hazard {hazard_id} does not exist")
        kind = hz["kind"]
        if kind not in HAZARD_KINDS:
            raise ActionsError(f"hazard {hazard_id} has unknown kind {kind!r}")

        types = {r["id"]: r["type"] for r in c.execute("SELECT id, type FROM objects")}
        impacts = [dict(r) for r in c.execute(
            "SELECT id, object_id, state FROM impacts WHERE hazard_id=?", (hazard_id,))]

        clear_actions(c, hazard_id)               # invariant 5: rebuild, never append

        fired, uncovered = 0, []
        # sorted: identical rows in identical order on every run (invariant 1)
        for imp in sorted(impacts, key=lambda i: (i["object_id"], i["id"])):
            oid, state = imp["object_id"], imp["state"]

            otype = types.get(oid)
            if otype is None:                     # an impact on nothing (D-028's cousin)
                raise ActionsError(f"impact {imp['id']} targets unknown object {oid!r}")
            if state not in STATE_ORDER or state == "OK":
                raise ActionsError(f"impact {imp['id']} on {oid}: state {state!r} is "
                                   f"outside the ontology (invariant 4)")

            rows = book.get((otype, state, kind), [])
            if not rows:
                uncovered.append({"object_id": oid, "object_type": otype, "state": state})
                continue
            for row in rows:
                c.execute("INSERT INTO actions (impact_id, action_text, owner_role, "
                          "lead_time_hrs, status) VALUES (?,?,?,?,?)",
                          (imp["id"], row["action_text"], row["owner_role"],
                           row["lead_time_hrs"], "PROPOSED"))
                fired += 1

    return {"hazard_id": hazard_id, "hazard_kind": kind,
            "impacts": len(impacts), "actions": fired,
            "uncovered": sorted(uncovered, key=lambda u: (u["object_type"],
                                                          u["state"], u["object_id"])),
            "playbook_version": PLAYBOOK_VERSION}


def generate(hazard_id: int) -> dict:
    """Phase 0 name, kept because app/main.py calls it at two endpoints.

    Identical to fire_actions(). New code should call fire_actions() - the name
    says what it does: it fires the committee's playbook, it does not *generate*
    anything. Retire this alias when main.py is rewritten (Phase 2 item 3).
    """
    return fire_actions(hazard_id)


# ------------------------------------------------------- consequence (read-side, derived)

def _dependents(c, hazard_id):
    """object_id -> how many ISOLATED settlements name it in their why-chain.

    Derived, never stored: it is a fact about the impacts of THIS hazard, and it
    must be re-derivable from them. Counting is over ISOLATED settlement impacts
    only - the engine has already proved each of those chains (invariant 2), so
    membership in one is proof that this object stands between that village and
    a facility it lost. Nothing is inferred, nothing is modelled.
    """
    dep = {}
    for r in c.execute("SELECT object_id, state, why_chain_json FROM impacts "
                       "WHERE hazard_id=? AND state='ISOLATED'", (hazard_id,)):
        for oid in set(json.loads(r["why_chain_json"])):
            dep[oid] = dep.get(oid, 0) + 1
    return dep


def _carrier_counts(c):
    """crossing id -> number of vehicle roads that `carries` it."""
    return {r["dst"]: r["n"] for r in c.execute(
        "SELECT dst, COUNT(*) n FROM links WHERE type='carries' GROUP BY dst")}


def actions_for(hazard_id: int):
    """Every action of one hazard, joined to its impact. Read-only, for the UI.

    Ordered by CONSEQUENCE first, lead time second (D-045). Sorting by lead time
    alone puts three unnamed ford nodes at 12 h above the B112 bridge at 24 h -
    six identical closure orders for crossings that isolate nobody, printed above
    the deck that cuts fifty-one villages. Urgency is not consequence.

    Two derived fields ride along, both computed from the graph and the engine's
    own why-chains:
      * `consequence` - ISOLATED settlements whose route this object blocks.
      * `carriers`    - vehicle roads linked to this crossing (bridges only).
      * `precautionary` - consequence == 0. The action still fires, and still
        carries its full weight: a flooded ford is a hazard to whoever drives
        into it. Zero dependents means only that no village in THIS graph loses
        a route through it - either it truly carries no vehicle road, or our link
        inference never found the road it sits on (7 bare OSM ford nodes have no
        carrier within 100 m). A gap in our data may never silence a warning
        (invariant 6), so the flag explains the action; it does not suppress it.
    """
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT a.id, a.impact_id, a.action_text, a.owner_role, a.lead_time_hrs, "
            "a.status, i.object_id, i.state, i.why_chain_json, "
            "o.type AS object_type, o.name AS object_name "
            "FROM actions a JOIN impacts i ON i.id = a.impact_id "
            "JOIN objects o ON o.id = i.object_id "
            "WHERE i.hazard_id=?", (hazard_id,))]
        dep = _dependents(c, hazard_id)
        carr = _carrier_counts(c)

    for a in rows:
        a["consequence"] = dep.get(a["object_id"], 0)
        a["carriers"] = (carr.get(a["object_id"], 0)
                         if a["object_type"] == "bridge" else None)
        a["precautionary"] = (a["consequence"] == 0)

    rows.sort(key=lambda a: (-a["consequence"], a["lead_time_hrs"],
                             a["object_id"], a["owner_role"], a["action_text"]))
    return rows


# --------------------------------------------------------------------------- cli

def _main(argv):
    if len(argv) == 2 and argv[1] == "--validate":
        book = load_playbook()
        print(f"{PLAYBOOK_VERSION}: OK")
        print(f"{sum(len(v) for v in book.values())} actions over "
              f"{len(book)} (object_type, state, hazard_kind) triples")
        for k in sorted(book):
            print("  ", "/".join(k), "->", len(book[k]))
        return 0
    if len(argv) == 2 and argv[1].isdigit():
        res = fire_actions(int(argv[1]))
        print(res["playbook_version"])
        print(f"hazard {res['hazard_id']} ({res['hazard_kind']}): "
              f"{res['impacts']} impacts -> {res['actions']} actions")
        if res["uncovered"]:
            print(f"UNCOVERED ({len(res['uncovered'])} impacts, no playbook row):")
            for u in res["uncovered"]:
                print("   ", u["object_type"], u["state"], u["object_id"])
        else:
            print("every impact has at least one action")
        rows = actions_for(int(argv[1]))
        prec = sum(1 for a in rows if a["precautionary"])
        print(f"{prec} of {len(rows)} actions are precautionary "
              f"(consequence 0: no village in this graph loses a route through them)")
        print("--- by consequence, then lead time:")
        for a in rows[:8]:
            label = a["object_name"] or a["object_id"]
            print(f"  {a['consequence']:>3} dep  {a['lead_time_hrs']:>3}h  "
                  f"{label[:28]:<28} {a['state']:<18} {a['owner_role']}")
        return 0
    print("usage: python -m app.actions <hazard_id> | --validate", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
