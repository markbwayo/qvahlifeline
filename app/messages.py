"""Broadcast messages. Committee words, engine slots, no model. Ever.

The last mile is a chief with a radio and a phone. What reaches him is the only
output of this system that a judge cannot audit, because it is not in English.
So it is not generated:

  * The SENTENCE comes from `data/messages.csv`, written by the district committee
    and by an engineer who speaks the language. It is data, like the playbook.
  * The FACTS come from the impact's own why-chain and from nowhere else. Not from
    a second traversal of the graph, not from a regex over `trigger_detail`, not
    from a model.
  * The AI edge may later draft an English polish or a Swahili translation, marked
    DRAFT and human-approved (07). It never sees this file's output as authority
    and never writes back into it.

Three refusals worth stating out loud, each a test:

  * **A slot that cannot be filled RAISES.** "The road from  to  crosses " is worse
    than no message. A broadcast is not a template with holes.
  * **A `lum` template with no `en` template for the same triple is refused at
    load.** English is what the system degrades to when a translation is missing;
    a local template with nothing behind it degrades to silence.
  * **An impact that a village must be warned about, and for which no template
    exists, is reported by name.** A settlement that is ISOLATED and has no message
    in its own language must appear on the officer's screen as a gap. Silence and
    safety look identical otherwise (invariant 6).
  * **A crossing broadcast as a bare OSM way id is reported too** (`needs_name`).
    The message renders - a labelled id beats silence - but "the road crosses
    w747829218" is not a sentence a chief can act on, and only an operator with
    satellite imagery can fix it. The gap is a CSV edit, and it is visible.

What may NOT appear in a broadcast, enforced by the slot whitelist in `ontology`:
  * `lead_time_hrs` - the playbook's completion deadline for an OWNER. The district
    engineer's 24 h is how long HE needs, not how long the water takes (D-051).
  * the return period and the m³/s threshold - they are prose inside
    `trigger_detail`, not columns. Pulling them back out with a regex is read-side
    re-inference, which is how D-046 happened.
"""
import csv
import json
import os
import string
import sys

from . import db
from .ontology import (BROADCAST_STATES, CAP_CERTAINTY_ASSUMED,
                       CAP_CERTAINTY_KNOWN, CAP_SEVERITY, CAP_URGENCY,
                       HAZARD_KINDS, MESSAGE_SLOTS, OBJECT_TYPES, STATE_ORDER,
                       TEMPLATE_LANGS)

MESSAGES_VERSION = "messages v1.0 (2026-07) - riverine_flood, Manafwa pilot"
MESSAGES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "messages.csv")

COLUMNS = ["object_type", "state", "hazard_kind", "lang", "template"]

# The engine has PROVED there is no alternate road (D-038: Old Manafwa bridge
# fails in the same flood). A message that offers one contradicts the proof, and
# unlike a playbook row - read by an engineer - this text is read by a village.
ALTERNATE_PHRASES = ("alternate route", "alternative route", "detour",
                     "reroute", "another route", "other road")


class MessageError(Exception):
    pass


# ------------------------------------------------------------------- the loader

def _slots(template):
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def load_messages(path=None):
    """(object_type, state, hazard_kind, lang) -> template. Validated hard."""
    path = path or MESSAGES_PATH
    if not os.path.exists(path):
        raise MessageError(f"messages file not found: {path}")

    book, seen = {}, set()
    with open(path, newline="", encoding="utf-8") as fh:
        rdr = csv.DictReader(fh)
        if rdr.fieldnames != COLUMNS:
            raise MessageError(f"columns must be {COLUMNS}, got {rdr.fieldnames}")
        for n, row in enumerate(rdr, start=2):
            otype = (row["object_type"] or "").strip()
            state = (row["state"] or "").strip()
            kind = (row["hazard_kind"] or "").strip()
            lang = (row["lang"] or "").strip()
            tmpl = (row["template"] or "").strip()

            def bad(msg):
                return MessageError(f"{path} line {n}: {msg}")

            if otype not in OBJECT_TYPES:
                raise bad(f"unknown object_type {otype!r}")
            if state not in STATE_ORDER or state == "OK":
                raise bad(f"unknown or impossible state {state!r}")
            if kind not in HAZARD_KINDS:
                raise bad(f"unknown hazard_kind {kind!r}")
            if lang not in TEMPLATE_LANGS:
                raise bad(f"lang must be one of {TEMPLATE_LANGS}, got {lang!r}")
            if not tmpl:
                raise bad("empty template")
            # A message for a state nobody is broadcast about is a policy change
            # dressed as a data edit. It goes through ontology.BROADCAST_STATES
            # and through 09, never through this file.
            if (otype, state) not in BROADCAST_STATES:
                raise bad(f"({otype}, {state}) is not a BROADCAST_STATE; "
                          f"add it to the ontology and 09 first")

            allowed = MESSAGE_SLOTS.get(otype, set())
            unknown = _slots(tmpl) - allowed
            if unknown:
                raise bad(f"unknown slot(s) {sorted(unknown)} for {otype}; "
                          f"allowed: {sorted(allowed)}")
            if state == "ISOLATED":
                low = tmpl.lower()
                hit = [p for p in ALTERNATE_PHRASES if p in low]
                if hit:
                    raise bad(f"an ISOLATED message may not offer a road alternate "
                              f"{hit}; the BFS proved there is none (D-038)")

            key = (otype, state, kind, lang)
            if key in seen:
                raise bad(f"duplicate row for {key}")
            seen.add(key)
            book[key] = tmpl

    # English is the floor. A translation with nothing behind it degrades to
    # silence, not to English.
    for (otype, state, kind, lang) in sorted(book):
        if lang != "en" and (otype, state, kind, "en") not in book:
            raise MessageError(
                f"{path}: {lang!r} template for ({otype}, {state}, {kind}) has no "
                f"'en' template behind it. English is what the system degrades to.")
    return book


def template_triples(path=None):
    return set(load_messages(path))


# --------------------------------------------------------------------- the facts

def _hazard(c, hazard_id):
    hz = c.execute("SELECT * FROM hazards WHERE id=?", (hazard_id,)).fetchone()
    if hz is None:
        raise MessageError(f"hazard {hazard_id} not found")
    return hz


def _certainty(c, hazard_id, crossing_id):
    """CAP certainty, read from the crossing's OWN why-chain.

    D-027 makes the engine declare `assumed_structure:ford(unclassified)` when it
    scored a crossing nobody classified. That confession is the confidence of every
    warning that depends on the crossing. It is read here, never re-derived: a
    settlement's chain does not carry the token, the crossing's does.
    """
    if not crossing_id:
        return CAP_CERTAINTY_ASSUMED          # we could not name the blocker: least confident
    row = c.execute("SELECT why_chain_json FROM impacts WHERE hazard_id=? AND "
                    "object_id=?", (hazard_id, crossing_id)).fetchone()
    if row is None:
        return CAP_CERTAINTY_ASSUMED
    chain = json.loads(row["why_chain_json"])
    assumed = any(str(x).startswith("assumed_structure:") for x in chain)
    return CAP_CERTAINTY_ASSUMED if assumed else CAP_CERTAINTY_KNOWN


def _label(oid, name):
    return name if (name or "").strip() else oid


def facts_for(impact_id):
    """Every fact a template may use, read from this impact's own why-chain.

    Never by position: a why-chain names a road only when a road was actually
    SEVERED (D-042), so `chain[3]` is a bridge in one impact and a settlement in
    the next. Objects are identified by TYPE.
    """
    with db.conn() as c:
        imp = c.execute("SELECT * FROM impacts WHERE id=?", (impact_id,)).fetchone()
        if imp is None:
            raise MessageError(f"impact {impact_id} not found")
        hz = _hazard(c, imp["hazard_id"])
        obj = c.execute("SELECT * FROM objects WHERE id=?",
                        (imp["object_id"],)).fetchone()
        if obj is None:
            raise MessageError(f"impact {impact_id} names a missing object "
                               f"{imp['object_id']!r}")

        chain = json.loads(imp["why_chain_json"])
        ids = [x for x in chain if not str(x).startswith(
            ("hazard:", "assumed_structure:", "alternate_via:"))]
        rows = {r["id"]: r for r in c.execute(
            "SELECT id, type, name, props_json FROM objects WHERE id IN "
            "(%s)" % ",".join("?" * len(ids)), ids)} if ids else {}

        crossing = next((rows[i] for i in ids
                         if i in rows and rows[i]["type"] == "bridge"), None)
        facility = next((rows[i] for i in reversed(ids)
                         if i in rows and rows[i]["type"] in
                         ("clinic", "school", "water_point")), None)

        f = {
            "hazard": hz["kind"].replace("_", " "),
            "severity": hz["severity"],
            "crossing": _label(crossing["id"], crossing["name"]) if crossing else "",
            "structure": (json.loads(crossing["props_json"] or "{}").get("structure")
                          or "unclassified crossing") if crossing else "",
        }
        if obj["type"] == "settlement":
            f["settlement"] = _label(obj["id"], obj["name"])
            f["facility"] = _label(facility["id"], facility["name"]) if facility else ""
            f["facility_type"] = facility["type"] if facility else ""
            # D-046's lesson: a settlement stores ONE chain, so a village that lost
            # its clinic AND its school records only the clinic. Every facility that
            # named this settlement in its own SERVICE_AT_RISK chain is read back.
            lost = []
            for r in c.execute("SELECT o.name, o.id FROM impacts i JOIN objects o "
                               "ON o.id=i.object_id WHERE i.hazard_id=? AND "
                               "i.state='SERVICE_AT_RISK' ORDER BY o.id",
                               (imp["hazard_id"],)):
                ch = c.execute("SELECT why_chain_json FROM impacts WHERE hazard_id=? "
                               "AND object_id=?", (imp["hazard_id"], r["id"])).fetchone()
                if obj["id"] in json.loads(ch["why_chain_json"]):
                    lost.append(_label(r["id"], r["name"]))
            f["facilities"] = ", ".join(lost)

        meta = {
            "impact_id": impact_id, "hazard_id": imp["hazard_id"],
            "object_id": obj["id"], "object_type": obj["type"], "state": imp["state"],
            "crossing_id": crossing["id"] if crossing else None,
            # An OSM way id on a map is a credibility leak. An OSM way id read
            # aloud to a chief is not a warning - it is noise. The message still
            # renders (a labelled id beats silence), and the gap is REPORTED so
            # an operator can name the crossing in operator_crossings.csv. A gap
            # the officer can see is not the same failure as one nobody knows of.
            "crossing_named": bool(crossing and (crossing["name"] or "").strip()),
            "certainty": _certainty(c, imp["hazard_id"],
                                    crossing["id"] if crossing else None),
        }

        # CAP 1.2. `instruction` carries the committee's action text VERBATIM -
        # the only correct home for it. Prose would have to paraphrase it.
        instr = [r["action_text"] for r in c.execute(
            "SELECT action_text FROM actions WHERE impact_id=? "
            "ORDER BY lead_time_hrs, owner_role, action_text", (impact_id,))]
        meta["cap"] = {
            "event": f"{hz['kind']} ({hz['severity']})",
            "urgency": CAP_URGENCY,               # we do not model arrival time (D-051)
            "severity": CAP_SEVERITY[hz["severity"]],
            "certainty": meta["certainty"],
            "area": _label(obj["id"], obj["name"]),
            "instruction": instr,
        }
    return f, meta


# ------------------------------------------------------------------- the renderer

def render(impact_id, lang="en", path=None, book=None):
    """Fill a committee template with engine facts. An empty slot RAISES.

    `book` may be a preloaded template map (from `load_messages`). `messages_for`
    passes it so the CSV is parsed and validated ONCE per page, not once per
    village - 72 broadcasts on the real graph. A None `book` loads and validates
    as before, so a direct `render()` call keeps its own guarantee.
    """
    if book is None:
        book = load_messages(path)
    f, meta = facts_for(impact_id)
    with db.conn() as c:
        kind = _hazard(c, meta["hazard_id"])["kind"]
    key = (meta["object_type"], meta["state"], kind, lang)
    tmpl = book.get(key)
    if tmpl is None:
        raise MessageError(f"no {lang!r} template for {key[:3]}")

    for slot in sorted(_slots(tmpl)):
        if not str(f.get(slot, "")).strip():
            raise MessageError(
                f"impact {impact_id}: slot {{{slot}}} is empty. A broadcast with a "
                f"hole in it is worse than no broadcast.")
    # `facts` rides along so a caller (the AI edge) can check that the proper
    # names the ENGINE produced survived a translation - a check against the
    # graph, never against the prose.
    return dict(meta, lang=lang, text=tmpl.format(**f), facts=f,
                template_version=MESSAGES_VERSION)


def messages_for(hazard_id, lang="en", path=None):
    """Every broadcast this hazard requires, and every one it cannot produce.

    `missing`  - the committee has written no template in this language. The
                 village is warned in English or not at all, and the officer sees
                 which villages those are, by name.
    `errors`   - a template exists and the facts will not fill it. A bug, shown.
    """
    with db.conn() as c:
        rows = c.execute(
            "SELECT i.id, i.object_id, i.state, o.type AS otype, o.name "
            "FROM impacts i JOIN objects o ON o.id=i.object_id "
            "WHERE i.hazard_id=? ORDER BY i.object_id", (hazard_id,)).fetchall()
        kind = _hazard(c, hazard_id)["kind"]

    book = load_messages(path)          # parsed and validated ONCE for the page
    out, missing, errors, skipped = [], [], [], 0
    unnamed = {}
    for r in rows:
        if (r["otype"], r["state"]) not in BROADCAST_STATES:
            skipped += 1
            continue
        who = {"impact_id": r["id"], "object_id": r["object_id"],
               "label": _label(r["object_id"], r["name"]), "state": r["state"]}
        if (r["otype"], r["state"], kind, lang) not in book:
            missing.append(who)
            continue
        try:
            m = render(r["id"], lang, path, book=book)
        except MessageError as e:
            errors.append(dict(who, error=str(e)))
            continue
        out.append(m)
        if m["crossing_id"] and not m["crossing_named"]:
            u = unnamed.setdefault(m["crossing_id"],
                                   {"crossing_id": m["crossing_id"], "broadcasts": 0})
            u["broadcasts"] += 1

    return {"hazard_id": hazard_id, "lang": lang, "messages": out,
            "missing": missing, "errors": errors, "not_broadcast": skipped,
            "needs_name": [unnamed[k] for k in sorted(unnamed)]}


# ------------------------------------------------------------------------- CLI

def _cli(argv):
    if "--validate" in argv:
        book = load_messages()
        langs = sorted({k[3] for k in book})
        print(f"{MESSAGES_VERSION}: {len(book)} templates, langs {langs}, OK")
        for lang in langs:
            n = sum(1 for k in book if k[3] == lang)
            print(f"  {lang}: {n} template(s)")
        return 0
    if not argv:
        print("usage: python -m app.messages <hazard_id> [--lang en] | --validate")
        return 2
    hid = int(argv[0])
    lang = argv[argv.index("--lang") + 1] if "--lang" in argv else "en"
    res = messages_for(hid, lang)
    print(f"hazard {hid}, lang {lang}: {len(res['messages'])} message(s), "
          f"{len(res['missing'])} missing, {len(res['errors'])} error(s), "
          f"{res['not_broadcast']} impact(s) not broadcast")
    for m in res["messages"]:
        print(f"\n[{m['object_id']}] {m['state']} "
              f"(CAP {m['cap']['severity']}/{m['cap']['certainty']}/"
              f"{m['cap']['urgency']})\n  {m['text']}")
        for i in m["cap"]["instruction"]:
            print(f"  - {i}")
    for m in res["missing"]:
        print(f"\nMISSING {lang}: {m['label']} ({m['state']})")
    for e in res["errors"]:
        print(f"\nERROR {e['label']}: {e['error']}")
    for n in res["needs_name"]:
        print(f"\nNEEDS NAME: {n['crossing_id']} is broadcast to "
              f"{n['broadcasts']} audience(s) as a bare object id. Name it in "
              f"data/operator_crossings.csv.")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
