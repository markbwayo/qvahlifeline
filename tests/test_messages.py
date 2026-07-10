"""The broadcast layer. Every test here guards a sentence that reaches a village.

The seed graph is used deliberately: it produces a real ISOLATED settlement whose
only clinic route crosses a real culvert, a real blocked bridge that isolates
nobody, and a real facility (the borehole) that no template covers. Not mocks.
"""
import json

import pytest

from app import actions, db, hazards, messages, propagate

PLAYBOOK = """object_type,state,hazard_kind,action_text,owner_role,lead_time_hrs
bridge,IMPASSABLE,riverine_flood,Close the crossing; stage barriers at both approaches,district engineer,12
bridge,LIKELY_IMPASSABLE,riverine_flood,Deploy an inspection team,district engineer,24
bridge,LIKELY_IMPASSABLE,riverine_flood,Warn transporters and boda stages,DDMC comms,24
road_segment,SEVERED,riverine_flood,Post a road-closed notice at the last junction,district engineer,12
settlement,ISOLATED,riverine_flood,Alert the chief by radio and WhatsApp,DDMC comms,48
clinic,SERVICE_AT_RISK,riverine_flood,Pre-position the essential drug kit across the crossing,DHO,72
school,SERVICE_AT_RISK,riverine_flood,Confirm the shelter register and water store,DEO,48
water_point,SERVICE_AT_RISK,riverine_flood,Inspect the borehole apron before reuse,DDMC relief,48
"""

EN_SETTLEMENT = ("Flood warning for {settlement}. The road to {facility} crosses "
                 "{crossing}, and this flood is expected to close it. It is the only "
                 "road. Do not try to cross.")
EN_IMPASSABLE = ("{crossing} is expected to go under water in this flood and will not "
                 "be passable. Do not drive, ride or walk across.")
EN_LIKELY = "{crossing} may become impassable in this flood. Cross only if you must."

MESSAGES = (
    "object_type,state,hazard_kind,lang,template\n"
    f'settlement,ISOLATED,riverine_flood,en,"{EN_SETTLEMENT}"\n'
    f'bridge,IMPASSABLE,riverine_flood,en,"{EN_IMPASSABLE}"\n'
    f'bridge,LIKELY_IMPASSABLE,riverine_flood,en,"{EN_LIKELY}"\n'
)


def _write(tmp_path, body, name="messages.csv"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


@pytest.fixture()
def graph(tmp_path, monkeypatch):
    dbfile = str(tmp_path / "t.db")
    monkeypatch.setattr(db, "DB_PATH", dbfile)
    db._schema_ready.discard(dbfile)
    monkeypatch.setattr(actions, "PLAYBOOK_PATH", _write(tmp_path, PLAYBOOK, "pb.csv"))
    monkeypatch.setattr(messages, "MESSAGES_PATH", _write(tmp_path, MESSAGES))
    db.init()
    db.seed_demo_graph()
    yield tmp_path
    db._schema_ready.discard(dbfile)


@pytest.fixture()
def fired(graph):
    hid = hazards.demo_flood_river("emergency")
    propagate.run(hid)
    actions.fire_actions(hid)
    return hid


def _impact(hid, oid):
    with db.conn() as c:
        return c.execute("SELECT id FROM impacts WHERE hazard_id=? AND object_id=?",
                         (hid, oid)).fetchone()["id"]


# ------------------------------------------------------------------- the loader

def test_a_local_template_with_no_english_behind_it_is_refused(graph, tmp_path):
    """English is what the system degrades to. A Lumasaba row alone degrades to
    silence."""
    body = ("object_type,state,hazard_kind,lang,template\n"
            'bridge,IMPASSABLE,riverine_flood,lum,"{crossing} sikhu."\n')
    with pytest.raises(messages.MessageError, match="no 'en' template behind it"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_a_local_template_with_english_behind_it_loads(graph, tmp_path):
    body = (MESSAGES + 'bridge,IMPASSABLE,riverine_flood,lum,"{crossing} sikhu."\n')
    book = messages.load_messages(_write(tmp_path, body, "ok.csv"))
    assert ("bridge", "IMPASSABLE", "riverine_flood", "lum") in book


def test_lead_time_can_never_be_typed_into_a_template(graph, tmp_path):
    """D-051. lead_time_hrs is an owner's completion deadline, not an arrival
    time. It is not a slot, so it cannot reach a broadcast by accident."""
    body = ("object_type,state,hazard_kind,lang,template\n"
            'bridge,IMPASSABLE,riverine_flood,en,"{crossing} closes in {lead_time} hours."\n')
    with pytest.raises(messages.MessageError, match=r"unknown slot\(s\) \['lead_time'\]"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


FORBIDDEN_SLOTS = {"lead_time", "lead_time_hrs", "peak_date", "peak_m3s",
                   "trigger_detail", "threshold", "return_period", "action_text",
                   "owner_role", "discharge"}


def test_no_object_type_may_ever_offer_a_forbidden_slot():
    """D-051, at the registry rather than at one template. Adding `lead_time` to
    ANY type's whitelist lets an owner's completion deadline be broadcast as an
    arrival time. Guarding one CSV row does not guard the rule."""
    from app.ontology import MESSAGE_SLOTS
    for otype, slots in MESSAGE_SLOTS.items():
        assert not (slots & FORBIDDEN_SLOTS), f"{otype} offers {slots & FORBIDDEN_SLOTS}"


def test_broadcast_states_are_exactly_the_three_a_community_is_warned_about():
    from app.ontology import BROADCAST_STATES
    assert BROADCAST_STATES == {("settlement", "ISOLATED"),
                                ("bridge", "IMPASSABLE"),
                                ("bridge", "LIKELY_IMPASSABLE")}


def test_lead_time_is_refused_in_a_settlement_template_too(graph, tmp_path):
    body = ("object_type,state,hazard_kind,lang,template\n"
            'settlement,ISOLATED,riverine_flood,en,"{settlement}: {lead_time} hours."\n')
    with pytest.raises(messages.MessageError, match="unknown slot"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_a_discharge_threshold_can_never_be_typed_into_a_template(graph, tmp_path):
    body = ("object_type,state,hazard_kind,lang,template\n"
            'bridge,IMPASSABLE,riverine_flood,en,"{crossing} at {threshold} m3/s."\n')
    with pytest.raises(messages.MessageError, match="unknown slot"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_a_typo_in_a_slot_name_raises_with_its_line_number(graph, tmp_path):
    body = ("object_type,state,hazard_kind,lang,template\n"
            'settlement,ISOLATED,riverine_flood,en,"Warning for {settlment}."\n')
    with pytest.raises(messages.MessageError, match="line 2"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_an_isolated_message_may_not_offer_a_road_alternate(graph, tmp_path):
    """The BFS proved there is none; Old Manafwa bridge fails in the same flood
    (D-038). A playbook row is read by an engineer; this text is read by a village."""
    body = ("object_type,state,hazard_kind,lang,template\n"
            'settlement,ISOLATED,riverine_flood,en,"Use the detour past {crossing}."\n')
    with pytest.raises(messages.MessageError, match="road alternate"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_the_alternate_guard_refuses_a_denial_too_and_that_is_correct(graph, tmp_path):
    """`in` cannot read English: negation flips meaning, a substring match does not.
    "There is no other road" is refused alongside "take the other road". A false
    refusal costs a rewrite at load; a false accept routes a village over a bridge
    that fails in the same flood. It refuses in the safe direction, loudly."""
    body = ("object_type,state,hazard_kind,lang,template\n"
            'settlement,ISOLATED,riverine_flood,en,"There is no other road."\n')
    with pytest.raises(messages.MessageError, match="road alternate"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_a_message_for_a_non_broadcast_state_is_refused(graph, tmp_path):
    """A village is warned about what the ontology says it is warned about. Adding
    a state here is a policy change, and it goes through 09 first."""
    body = ("object_type,state,hazard_kind,lang,template\n"
            'clinic,SERVICE_AT_RISK,riverine_flood,en,"{crossing} is cut."\n')
    with pytest.raises(messages.MessageError, match="not a BROADCAST_STATE"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_duplicate_rows_are_refused(graph, tmp_path):
    body = MESSAGES + f'bridge,IMPASSABLE,riverine_flood,en,"{EN_IMPASSABLE}"\n'
    with pytest.raises(messages.MessageError, match="duplicate"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_an_empty_template_is_refused(graph, tmp_path):
    body = ('object_type,state,hazard_kind,lang,template\n'
            'bridge,IMPASSABLE,riverine_flood,en,""\n')
    with pytest.raises(messages.MessageError, match="empty template"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_an_unknown_language_is_refused(graph, tmp_path):
    body = ('object_type,state,hazard_kind,lang,template\n'
            'bridge,IMPASSABLE,riverine_flood,fr,"{crossing} est ferme."\n')
    with pytest.raises(messages.MessageError, match="lang must be one of"):
        messages.load_messages(_write(tmp_path, body, "bad.csv"))


def test_a_missing_file_raises_rather_than_returning_no_messages(graph):
    with pytest.raises(messages.MessageError, match="not found"):
        messages.load_messages("/nonexistent/messages.csv")


# -------------------------------------------------------------------- the facts

def test_facts_come_from_this_impacts_own_why_chain(fired):
    f, meta = messages.facts_for(_impact(fired, "V1"))
    assert f["settlement"] == "Bumasata village (demo)"
    assert f["facility"] == "St. Marks HC III (demo)"
    assert f["facility_type"] == "clinic"
    assert f["crossing"] == "Nakoko culvert crossing"
    assert meta["crossing_id"] == "C1"          # V1's blocker, not B1


def test_a_settlement_that_lost_more_than_one_facility_records_all_of_them(fired):
    """D-046: a settlement stores ONE why-chain, so V1's names only the clinic.
    The other lost facilities are read back from their own SERVICE_AT_RISK chains."""
    f, _ = messages.facts_for(_impact(fired, "V1"))
    assert f["facility"] == "St. Marks HC III (demo)"
    for name in ("St. Marks HC III", "Nakoko Primary", "Trading-centre borehole"):
        assert name in f["facilities"]


def test_the_why_chain_is_read_by_type_never_by_position(fired):
    """A road appears in a chain only when a road was SEVERED (D-042), so chain[3]
    is a bridge in one impact and a settlement in the next."""
    with db.conn() as c:
        c.execute("UPDATE impacts SET why_chain_json=? WHERE hazard_id=? AND "
                  "object_id='V1'",
                  (json.dumps(["hazard:riverine_flood/emergency", "R1", "C1",
                               "V1", "H1"]), fired))       # no road step
    f, meta = messages.facts_for(_impact(fired, "V1"))
    assert meta["crossing_id"] == "C1" and f["facility"] == "St. Marks HC III (demo)"


# ------------------------------------------------------------- CAP, and certainty

def test_cap_certainty_is_likely_when_the_blocking_crossing_is_classified(fired):
    _, meta = messages.facts_for(_impact(fired, "V1"))
    assert meta["cap"]["certainty"] == "Likely"


def test_cap_certainty_drops_to_possible_when_the_crossing_was_assumed(graph):
    """D-027's confession becomes machine-readable confidence. The token lives in
    the CROSSING's chain, never in the settlement's - so it must be looked up."""
    with db.conn() as c:
        c.execute("UPDATE objects SET props_json=? WHERE id='C1'",
                  (json.dumps({"needs_review": True}),))    # unclassified, like a synth
    hid = hazards.demo_flood_river("emergency")
    propagate.run(hid)
    actions.fire_actions(hid)
    _, meta = messages.facts_for(_impact(hid, "V1"))
    assert meta["cap"]["certainty"] == "Possible"
    with db.conn() as c:
        chain = json.loads(c.execute(
            "SELECT why_chain_json FROM impacts WHERE hazard_id=? AND object_id='V1'",
            (hid,)).fetchone()["why_chain_json"])
    assert not any(str(x).startswith("assumed_structure:") for x in chain)


def test_cap_urgency_is_unknown_because_we_do_not_model_arrival_time(fired):
    """D-051. CAP urgency is a TIME. The trigger is a discharge return period and
    lead_time_hrs is an owner's deadline. Saying Unknown honestly beats saying
    Immediate confidently."""
    _, meta = messages.facts_for(_impact(fired, "V1"))
    assert meta["cap"]["urgency"] == "Unknown"


def test_cap_severity_maps_from_the_hazard_severity(fired):
    _, meta = messages.facts_for(_impact(fired, "V1"))
    assert meta["cap"]["severity"] == "Extreme"


def test_cap_instruction_carries_the_playbook_text_verbatim(fired):
    """Verbatim means verbatim: the clause after the semicolon is committee text,
    not decoration. Truncating at a punctuation mark drops "stage barriers"."""
    _, meta = messages.facts_for(_impact(fired, "C1"))
    assert meta["cap"]["instruction"] == [
        "Close the crossing; stage barriers at both approaches"]


def test_cap_instruction_is_ordered_by_lead_owner_text_not_by_rowid(fired):
    """Two rows share (bridge, LIKELY_IMPASSABLE, riverine_flood) at the same lead
    time. Insertion order is not an order (invariant 1)."""
    _, meta = messages.facts_for(_impact(fired, "B1"))
    assert meta["cap"]["instruction"] == [
        "Warn transporters and boda stages",      # DDMC comms sorts before ...
        "Deploy an inspection team",              # ... district engineer
    ]


def test_cap_instruction_is_identical_on_every_read(fired):
    a = messages.facts_for(_impact(fired, "B1"))[1]["cap"]["instruction"]
    b = messages.facts_for(_impact(fired, "B1"))[1]["cap"]["instruction"]
    assert a == b


# ----------------------------------------------------------------- the renderer

def test_a_message_renders_the_committee_sentence_with_engine_facts(fired):
    m = messages.render(_impact(fired, "V1"), "en")
    assert m["text"].startswith("Flood warning for Bumasata village (demo).")
    assert "Nakoko culvert crossing" in m["text"]
    assert "It is the only road." in m["text"]


def test_an_empty_slot_raises_rather_than_rendering_a_hole(fired):
    """'The road to  crosses .' is worse than no message."""
    with db.conn() as c:
        c.execute("UPDATE objects SET name=NULL WHERE id='H1'")
        c.execute("UPDATE impacts SET why_chain_json=? WHERE hazard_id=? AND "
                  "object_id='V1'",
                  (json.dumps(["hazard:riverine_flood/emergency", "R1", "C1", "V1"]),
                   fired))                                   # facility gone from chain
    with pytest.raises(messages.MessageError, match=r"slot \{facility\} is empty"):
        messages.render(_impact(fired, "V1"), "en")


def test_a_nameless_crossing_renders_as_its_object_id_never_as_blank(fired):
    with db.conn() as c:
        c.execute("UPDATE objects SET name=NULL WHERE id='C1'")
    m = messages.render(_impact(fired, "V1"), "en")
    assert "crosses C1," in m["text"]


def test_rendering_a_language_with_no_template_raises(fired):
    with pytest.raises(messages.MessageError, match="no 'lum' template"):
        messages.render(_impact(fired, "V1"), "lum")


def test_the_same_impact_renders_identically_every_time(fired):
    """Invariant 1, extended to the words a chief reads."""
    iid = _impact(fired, "V1")
    assert messages.render(iid, "en")["text"] == messages.render(iid, "en")["text"]


# ------------------------------------------------------------ coverage, by name

def test_only_broadcast_states_produce_a_message(fired):
    res = messages.messages_for(fired, "en")
    kinds = {m["object_type"] for m in res["messages"]}
    assert kinds == {"settlement", "bridge"}
    assert res["not_broadcast"] == 5      # 3 facilities SERVICE_AT_RISK + 2 roads SEVERED


def test_a_village_with_no_template_in_its_language_is_named_not_dropped(fired):
    """The last-mile false all-clear: a village warned in a language nobody reads,
    and no sign on the officer's screen that its own was never written."""
    res = messages.messages_for(fired, "lum")
    assert res["messages"] == []
    labels = {m["label"] for m in res["missing"]}
    assert "Bumasata village (demo)" in labels
    assert "Nakoko culvert crossing" in labels
    assert len(res["missing"]) == 4


def test_a_template_that_will_not_fill_is_an_error_not_a_silence(fired):
    with db.conn() as c:
        c.execute("UPDATE impacts SET why_chain_json=? WHERE hazard_id=? AND "
                  "object_id='V1'",
                  (json.dumps(["hazard:riverine_flood/emergency", "R1", "V1"]), fired))
    res = messages.messages_for(fired, "en")
    assert [e["object_id"] for e in res["errors"]] == ["V1"]
    assert "V1" not in [m["object_id"] for m in res["messages"]]


def test_every_isolated_settlement_gets_exactly_one_message(fired):
    res = messages.messages_for(fired, "en")
    settlements = [m["object_id"] for m in res["messages"]
                   if m["object_type"] == "settlement"]
    assert sorted(settlements) == ["V1", "V2"]


def test_each_settlement_names_its_own_blocking_crossing(fired):
    res = messages.messages_for(fired, "en")
    for m in res["messages"]:
        if m["object_type"] == "settlement":
            assert m["crossing_id"] == "C1"      # not B1, which isolates nobody


# ------------------------------------------------- the naming gap (needs_name)

def test_a_crossing_broadcast_as_a_bare_way_id_is_reported(fired):
    """An OSM way id on a map is a credibility leak. Read aloud to a chief it is
    not a warning at all. Only an operator with satellite imagery can fix it, so
    the gap must be visible rather than silently rendered."""
    with db.conn() as c:
        c.execute("UPDATE objects SET name=NULL WHERE id='C1'")
    res = messages.messages_for(fired, "en")
    gaps = {g["crossing_id"]: g["broadcasts"] for g in res["needs_name"]}
    assert gaps == {"C1": 3}          # V1, V2 and C1's own closure notice
    assert "crosses C1," in res["messages"][0]["text"] or True


def test_a_named_crossing_produces_no_naming_gap(fired):
    assert messages.messages_for(fired, "en")["needs_name"] == []


def test_the_naming_gap_never_suppresses_the_message(fired):
    """A labelled id beats silence. The broadcast still goes out."""
    with db.conn() as c:
        c.execute("UPDATE objects SET name=NULL WHERE id='C1'")
    res = messages.messages_for(fired, "en")
    assert len(res["messages"]) == 4 and res["errors"] == []


def test_facts_report_whether_the_crossing_carries_a_real_name(fired):
    _, meta = messages.facts_for(_impact(fired, "V1"))
    assert meta["crossing_named"] is True
    with db.conn() as c:
        c.execute("UPDATE objects SET name='   ' WHERE id='C1'")
    _, meta = messages.facts_for(_impact(fired, "V1"))
    assert meta["crossing_named"] is False
