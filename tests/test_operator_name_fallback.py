r"""tests/test_operator_name_fallback.py - D-041: the demo spine must have a name.

OSM way w128611448 is the Manafwa Bridge (B112), the town's only tarmac crossing
and the object 51 of the 62 ISOLATED why-chains name. Its OSM tags are:

    "bridge": "yes", "bridge:name": "Manafwa Bridge",
    "bridge:ref": "B112", "noname": "yes"

There is no `name` tag - OSM deliberately says so with `noname=yes` and puts the
structure's name on `bridge:name`. Ingest reads tags.name, so the object's name is
NULL. Operator injection then obeyed 09 ("the OSM object's id, name and coordinates
are preserved") and faithfully preserved the NULL.

Result before this fix: the map and the why-chain panel rendered the demo spine as
the bare string `w128611448`, while the *least* important structure - Old Manafwa
bridge, which appears in ZERO isolated why-chains - was the only named bridge on
screen. Not a wrong impact, but a credibility leak in the one frame the judges watch.

The rule (09 v0.9): an OSM name is preserved only when it is NON-EMPTY. Otherwise the
operator's CSV name wins. `name_source` records which, so the provenance is auditable
and a real OSM name can never be silently overwritten by the operator's.
"""
import json

import pytest

from app import db, links


SPINE_TAGS = {
    "bridge": "yes",
    "bridge:name": "Manafwa Bridge",
    "bridge:ref": "B112",
    "highway": "secondary",
    "noname": "yes",
}

CSV_HEADER = "id,structure,name,lat,lon,road_class,source,note,match_hint\n"


def _csv(tmp_path, rows):
    p = tmp_path / "operator_crossings.csv"
    p.write_text(CSV_HEADER + "".join(rows), encoding="utf-8")
    return str(p)


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    return tmp_path


def _obj(oid):
    with db.conn() as c:
        r = c.execute("SELECT * FROM objects WHERE id=?", (oid,)).fetchone()
    return dict(r), json.loads(r["props_json"] or "{}")


def _add_osm_crossing(oid, name, lat, lon, tags):
    with db.conn() as c:
        db.add_object(c, oid, "bridge", name, lat, lon,
                      {"structure": "bridge", "tags": tags}, source="osm")


# --- the regression -------------------------------------------------------

def test_nameless_osm_crossing_takes_the_operator_name(graph):
    """THE bug. w128611448 has no OSM name; the operator's name must land on it."""
    _add_osm_crossing("w128611448", None, 0.9405294, 34.2802388, SPINE_TAGS)
    csv = _csv(graph, ["op_manafwa_tc_bridge,bridge,Manafwa Bridge (B112 town crossing),"
                       "0.9406239,34.2802124,main_road,operator,note,w128611448\n"])

    links.inject_operator_crossings(csv_path=csv)

    row, props = _obj("w128611448")
    assert row["name"] == "Manafwa Bridge (B112 town crossing)"
    assert row["name"] is not None and row["name"] != "w128611448"
    assert props["name_source"] == "operator"
    assert props["osm_name"] is None
    assert row["source"] == "operator"


def test_bridge_name_tag_is_captured_as_provenance(graph):
    """Why the name was empty must be visible: OSM put it on `bridge:name`."""
    _add_osm_crossing("w128611448", None, 0.9405294, 34.2802388, SPINE_TAGS)
    csv = _csv(graph, ["op_manafwa_tc_bridge,bridge,Manafwa Bridge (B112 town crossing),"
                       "0.9406239,34.2802124,main_road,operator,note,w128611448\n"])

    links.inject_operator_crossings(csv_path=csv)

    _, props = _obj("w128611448")
    assert props["osm_bridge_name"] == "Manafwa Bridge"
    # provenance, never authority: the object's name is the operator's.
    assert props["operator_name"] == "Manafwa Bridge (B112 town crossing)"


# --- the guard in the other direction -------------------------------------

def test_a_real_osm_name_is_never_overwritten(graph):
    """09: the OSM name is preserved. The fix must only fill a HOLE, never
    replace a real OSM name with the operator's - that would silently rewrite
    the map label the district already knows the structure by."""
    _add_osm_crossing("w902422828", "Old Manafwa bridge", 0.9407553, 34.2804554,
                      {"bridge": "yes", "name": "Old Manafwa bridge", "ref": "C870"})
    csv = _csv(graph, ["op_old,bridge,Some Operator Label,"
                       "0.9407553,34.2804554,minor_road,operator,note,w902422828\n"])

    links.inject_operator_crossings(csv_path=csv)

    row, props = _obj("w902422828")
    assert row["name"] == "Old Manafwa bridge"        # OSM wins
    assert props["name_source"] == "osm"
    assert props["operator_name"] == "Some Operator Label"   # kept, unused as label


def test_new_operator_object_is_named_from_the_csv(graph):
    """Path (5): nothing within 50 m -> a new operator object, named from the CSV."""
    csv = _csv(graph, ["op_north_footpath_culvert,culvert,North footpath culvert,"
                       "0.9564980,34.2896510,footpath,operator,note,\n"])

    links.inject_operator_crossings(csv_path=csv)

    row, props = _obj("op:op_north_footpath_culvert")
    assert row["name"] == "North footpath culvert"
    assert props["name_source"] == "operator"


# --- idempotence ----------------------------------------------------------

def test_reinjection_is_idempotent_and_does_not_flip_name_source(graph):
    """Run 2 sees a non-empty name (the operator's, from run 1). It must not
    then conclude the name came from OSM. Invariant 1: same inputs, same graph."""
    _add_osm_crossing("w128611448", None, 0.9405294, 34.2802388, SPINE_TAGS)
    csv = _csv(graph, ["op_manafwa_tc_bridge,bridge,Manafwa Bridge (B112 town crossing),"
                       "0.9406239,34.2802124,main_road,operator,note,w128611448\n"])

    links.inject_operator_crossings(csv_path=csv)
    row1, props1 = _obj("w128611448")
    links.inject_operator_crossings(csv_path=csv)
    row2, props2 = _obj("w128611448")

    assert row1["name"] == row2["name"] == "Manafwa Bridge (B112 town crossing)"
    assert props1["name_source"] == props2["name_source"] == "operator"
    assert props2["osm_name"] is None

    with db.conn() as c:
        n = c.execute("SELECT COUNT(*) n FROM objects WHERE type='bridge'").fetchone()["n"]
    assert n == 1                                    # no second object, ever


def test_reinjection_heals_an_already_injected_nameless_spine(graph):
    """The live DB already holds w128611448 as source=operator with name=NULL.
    Re-running `links.py inject` must repair it in place - path (1), not (2)."""
    with db.conn() as c:
        db.add_object(c, "w128611448", "bridge", None, 0.9405294, 34.2802388,
                      {"structure": "bridge", "crossing_class": "main_road",
                       "tags": SPINE_TAGS, "operator_id": "op_manafwa_tc_bridge",
                       "operator_verified": True,
                       "operator_name": "Manafwa Bridge (B112 town crossing)"},
                      source="operator")
    csv = _csv(graph, ["op_manafwa_tc_bridge,bridge,Manafwa Bridge (B112 town crossing),"
                       "0.9406239,34.2802124,main_road,operator,note,w128611448\n"])

    res = links.inject_operator_crossings(csv_path=csv)

    assert res[0][1] == "reinjected"
    row, props = _obj("w128611448")
    assert row["name"] == "Manafwa Bridge (B112 town crossing)"
    assert props["name_source"] == "operator"
