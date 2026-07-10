"""The AI edge. The only place a model speaks, and the smallest surface in the repo.

Two behaviours are opposites on purpose, and both are tested:

  * a REFUSAL raises (Lumasaba, an unknown language, an unknown task, an unknown
    payload key);
  * a FAILURE returns (no key, dead network, HTTP error, garbage response).

`hazards.scan_live()` is the mirror image: every feed failure raises, because a
dead gauge reporting "no hazard" is indistinguishable from a calm river. Losing
the forecast loses the warning. Losing the translator loses a convenience.

Three further properties are locked here, and each is a hole that existed:

  * D-057. A 429 or a 503 is retried once. A 400 or a 403 is NOT. The test that
    carries the decision is the second one, asserted on the call count - a test
    that only checks "a 429 retries" passes against code that retries everything.
  * D-058. `AI_EDGE_LIVE` gates this module and `USE_LIVE` does not. The fixture
    therefore runs the whole file at `USE_LIVE=0`, which is demo-day's setting.
  * D-059. The edge is told three keys and no more, its cache key covers the
    instruction it was given, and it imports nothing from the engine.
"""
import ast
import inspect
import json
import socket
import urllib.error

import pytest

from app import ai_edge, db

EN = "Manafwa Bridge may become impassable in this flood. Do not try to cross."
SW = "Daraja la Manafwa linaweza kufungwa. Usijaribu kuvuka."


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dbfile = str(tmp_path / "t.db")
    monkeypatch.setattr(db, "DB_PATH", dbfile)
    db._schema_ready.discard(dbfile)
    db.init()
    # D-058: the core is OFF and the edge is ON. This is the demo-day setting, and
    # running every live-path test under it proves the two gates are independent.
    monkeypatch.setenv("USE_LIVE", "0")
    monkeypatch.setenv("AI_EDGE_LIVE", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setattr(ai_edge, "_pause", lambda: None)   # no real 2 s in a suite
    yield monkeypatch
    db._schema_ready.discard(dbfile)


def _stub(monkeypatch, *replies):
    """Each reply is returned (or raised) on the corresponding attempt. The last
    reply repeats, so a single argument means `always this`."""
    calls = []

    def fake(prompt, model, key):
        calls.append({"prompt": prompt, "model": model, "key": key})
        r = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(ai_edge, "_call", fake)
    return calls


def _http(code, body=b"denied"):
    err = urllib.error.HTTPError("u", code, "err", {}, None)
    err.read = lambda: body
    return err


# ------------------------------------------------------- refusals: these RAISE

def test_the_edge_will_never_generate_lumasaba(env):
    """D-052. It reaches the last mile, every model is worst at it, and nobody in
    the room can audit it. A fluent mistranslation of 'do not cross' is an impact
    decision taken by a model."""
    with pytest.raises(ai_edge.AIEdgeRefused, match="never generate Lumasaba"):
        ai_edge.ai_edge("translate", {"text": EN, "target_lang": "lum"})


def test_an_unlisted_target_language_is_refused(env):
    with pytest.raises(ai_edge.AIEdgeRefused, match="target_lang must be one of"):
        ai_edge.ai_edge("translate", {"text": EN, "target_lang": "fr"})


def test_english_is_not_a_target(env):
    with pytest.raises(ai_edge.AIEdgeRefused):
        ai_edge.ai_edge("translate", {"text": EN, "target_lang": "en"})


def test_the_edge_does_exactly_one_task(env):
    with pytest.raises(ai_edge.AIEdgeRefused, match="unknown task"):
        ai_edge.ai_edge("decide_impact", {"text": EN, "target_lang": "sw"})
    assert ai_edge.TASKS == {"translate"}


def test_empty_text_is_refused(env):
    with pytest.raises(ai_edge.AIEdgeRefused, match="nothing to translate"):
        ai_edge.ai_edge("translate", {"text": "   ", "target_lang": "sw"})


# ------------------------------------- D-059: the edge is told three things, no more

def test_an_unknown_payload_key_is_refused_before_the_provider_is_called(env, monkeypatch):
    """Hard rule 1, mechanised. A later 'pass the impact id so we can log it' must
    not be able to put a graph identifier into a prompt without a test reddening."""
    calls = _stub(monkeypatch, SW)
    with pytest.raises(ai_edge.AIEdgeRefused, match="not permitted"):
        ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw",
                                      "impact_id": 41})
    assert calls == []


def test_the_permitted_payload_is_a_closed_set(env):
    assert ai_edge.PAYLOAD_KEYS == frozenset({"text", "target_lang", "preserve"})


def test_the_edge_module_imports_nothing_from_the_engine(env):
    """Structural. `db` is the sole allowance, and only for the draft cache. The
    edge cannot read an impact or write an action because it cannot reach them."""
    tree = ast.parse(inspect.getsource(ai_edge))
    imported = set()
    for node in tree.body:                       # module level only, on purpose
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
            imported.update(a.name for a in node.names)
    engine = {"propagate", "actions", "links", "ontology", "hazards", "messages",
              "ingest_osm", "main"}
    assert not (imported & engine), f"the edge imports {sorted(imported & engine)}"
    assert "db" in imported


# ---------------------------------------------- failures: these RETURN, never raise

def test_a_disabled_edge_returns_rather_than_raises(env):
    env.setenv("AI_EDGE_LIVE", "0")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge disabled (AI_EDGE_LIVE=0)"
    assert r["draft"] is None and r["approved"] is False


def test_a_missing_key_returns_rather_than_raises(env):
    env.delenv("GEMINI_API_KEY")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge unavailable" and r["reason"] == "no GEMINI_API_KEY"


def test_a_dead_network_never_raises(env, monkeypatch):
    """The English and Lumasaba text renders regardless: neither passes through a
    model. This is the architecture, not a fallback bolted onto it."""
    _stub(monkeypatch, urllib.error.URLError("connection refused"))
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge unavailable"
    assert "URLError" in r["reason"] and r["approved"] is False


def test_an_http_error_names_the_model_that_failed(env, monkeypatch):
    """Google moved 3.x Pro to paid-only in April 2026. A 404 on a model string
    must say WHICH string, or the fix is a guessing game at 2am."""
    _stub(monkeypatch, _http(404, b"model not found"))
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge unavailable" and "gemini-test" in r["reason"]


# ---------------------------------------------------------- D-058: the two switches

def test_the_edge_gate_defaults_to_off(env):
    env.delenv("AI_EDGE_LIVE")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge disabled (AI_EDGE_LIVE=0)"


def test_use_live_does_not_enable_the_edge(env, monkeypatch):
    """`USE_LIVE` guards the feed, whose failure is indistinguishable from calm
    water. It has never guarded this module and must not start."""
    calls = _stub(monkeypatch, SW)
    env.setenv("USE_LIVE", "1")
    env.delenv("AI_EDGE_LIVE")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge disabled (AI_EDGE_LIVE=0)"
    assert calls == []


def test_the_edge_runs_while_the_deterministic_core_is_offline(env, monkeypatch):
    """Demo day: USE_LIVE=0, AI_EDGE_LIVE=1. The flood comes from the graph
    because a dead feed must never look like a calm river; the Swahili comes from
    the model because a dead translator costs nothing."""
    _stub(monkeypatch, SW)
    assert env is not None
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "DRAFT"


def test_the_disabled_status_names_the_variable_that_would_enable_it(env):
    env.setenv("AI_EDGE_LIVE", "0")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert ai_edge.EDGE_LIVE_VAR in r["status"]


# ------------------------------------------------------------------ D-057: the retry

def test_a_429_is_retried_once_and_then_succeeds(env, monkeypatch):
    calls = _stub(monkeypatch, _http(429, b"rate limited"), SW)
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 2
    assert r["status"] == "DRAFT" and r["retried"] is True


def test_a_503_is_retried_once_and_then_succeeds(env, monkeypatch):
    """Observed live on gemini-2.5-flash in Session 22. Free-tier demand, and the
    single most likely demo-day failure."""
    calls = _stub(monkeypatch, _http(503, b"overloaded"), SW)
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 2 and r["status"] == "DRAFT"


def test_a_400_is_never_retried(env, monkeypatch):
    """THE test for D-057. A 429 means `come back`; a 400 means `you are wrong`,
    and retrying a wrong request is a way of not reading the error. Asserted on
    the call count: a code that retries everything passes a 429 test and fails
    this one."""
    calls = _stub(monkeypatch, _http(400, b"bad request"))
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 1
    assert r["status"] == "edge unavailable" and r["retried"] is False
    assert "HTTP 400" in r["reason"]


def test_a_403_is_never_retried(env, monkeypatch):
    """A rotated key that never reached .env. The presenter must see it in one
    second, not twenty-two."""
    calls = _stub(monkeypatch, _http(403, b"invalid api key"))
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 1 and "HTTP 403" in r["reason"]


def test_a_404_on_a_retired_model_is_never_retried(env, monkeypatch):
    calls = _stub(monkeypatch, _http(404, b"model not found"))
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 1


def test_a_persistent_503_retries_exactly_once_and_then_stops(env, monkeypatch):
    """One retry is a pause. A loop is a storm against a 10 RPM free tier."""
    calls = _stub(monkeypatch, _http(503, b"overloaded"))
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 2                       # not 3, not 5
    assert r["status"] == "edge unavailable" and r["retried"] is True
    assert ai_edge.MAX_ATTEMPTS == 2


def test_a_timeout_is_never_retried(env, monkeypatch):
    """A 429 is a prompt response; a hang is not, and offers no evidence a second
    attempt would return. 42 s of a two-minute demo is worse than English alone."""
    calls = _stub(monkeypatch, socket.timeout("timed out"))
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 1 and r["status"] == "edge unavailable"


def test_a_dead_network_is_never_retried(env, monkeypatch):
    calls = _stub(monkeypatch, urllib.error.URLError("connection refused"))
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 1


def test_the_retry_pauses_once_before_the_second_attempt(env, monkeypatch):
    pauses = []
    monkeypatch.setattr(ai_edge, "_pause", lambda: pauses.append(1))
    _stub(monkeypatch, _http(429, b"rate limited"), SW)
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(pauses) == 1
    assert ai_edge.RETRY_PAUSE_S == 2.0


def test_retry_status_is_exactly_429_and_503(env):
    assert ai_edge.RETRY_STATUS == frozenset({429, 503})
    for code in (400, 401, 403, 404, 500, 502):
        assert code not in ai_edge.RETRY_STATUS


def test_every_outcome_reports_whether_it_retried(env, monkeypatch):
    _stub(monkeypatch, SW)
    assert ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})["retried"] is False
    env.setenv("AI_EDGE_LIVE", "0")
    assert "retried" in ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})


# --------------------------------------------------- what a non-speaker can check

def test_a_good_translation_comes_back_as_a_draft_never_as_a_message(env, monkeypatch):
    _stub(monkeypatch, SW)
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "DRAFT"
    assert r["approved"] is False
    assert "human must approve" in r["note"]


def test_an_empty_draft_is_unusable(env, monkeypatch):
    _stub(monkeypatch, "")
    assert ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})[
        "status"] == "edge unusable"


def test_markdown_or_a_url_in_a_draft_is_unusable(env, monkeypatch):
    _stub(monkeypatch, "```\nsee https://example.com\n```")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge unusable"


def test_an_essay_is_not_a_translation(env, monkeypatch):
    _stub(monkeypatch, "kuvuka " * 200)
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge unusable" and "longer" in r["reason"]


def test_a_summary_is_not_a_translation(env, monkeypatch):
    """A model that returns three words dropped the instruction not to cross."""
    _stub(monkeypatch, "Usivuke.")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge unusable" and "shorter" in r["reason"]


def test_a_rejected_draft_is_returned_but_is_never_a_draft(env, monkeypatch):
    """`edge unusable` carries the text that failed, so an operator can judge the
    check. A caller renders it REJECTED. Only `status == DRAFT` is a draft."""
    _stub(monkeypatch, "Usivuke.")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["draft"] == "Usivuke." and r["status"] != "DRAFT"
    assert r["approved"] is False


def test_a_proper_name_lost_in_translation_is_surfaced_to_the_approver(env, monkeypatch):
    """The names come from the ENGINE's facts, so this checks the draft against
    the graph, never against the prose. It warns; only a human can reject."""
    _stub(monkeypatch, "Daraja fulani linaweza kufungwa. Usijaribu kuvuka sasa.")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw",
                                      "preserve": ["Manafwa Bridge"]})
    assert r["status"] == "DRAFT"
    assert any("Manafwa Bridge" in w for w in r["warnings"])


def test_a_preserved_name_that_survives_raises_no_warning(env, monkeypatch):
    _stub(monkeypatch, "Manafwa Bridge linaweza kufungwa. Usijaribu kuvuka sasa.")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw",
                                      "preserve": ["Manafwa Bridge"]})
    assert r["warnings"] == []


# ------------------------------------------------------------------------ the cache

def test_a_second_identical_request_does_not_touch_the_provider(env, monkeypatch):
    """10 requests per minute on the free tier, and 72 broadcasts on the real
    graph. Caching is not an optimisation."""
    calls = _stub(monkeypatch, SW)
    a = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    b = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 1
    assert a["draft"] == b["draft"] and b["cached"] is True


def test_a_bad_draft_is_never_cached(env, monkeypatch):
    calls = _stub(monkeypatch, "")
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 2


def test_a_failed_call_is_never_cached(env, monkeypatch):
    calls = _stub(monkeypatch, _http(503, b"overloaded"))
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 4                       # two attempts, twice. Nothing stored.


def test_changing_the_model_invalidates_the_cache(env, monkeypatch):
    calls = _stub(monkeypatch, SW)
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    env.setenv("GEMINI_MODEL", "gemini-other")
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 2


def test_changing_the_instruction_invalidates_the_cache(env, monkeypatch):
    """D-059. The system prompt is part of the input. Tune it after a rehearsal and
    a cached draft was produced under wording nobody recorded, in the one layer
    whose output a human signs."""
    calls = _stub(monkeypatch, SW)
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    monkeypatch.setattr(ai_edge, "SYSTEM", ai_edge.SYSTEM + " Be brief.")
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 2


def test_a_cached_draft_is_never_approved(env, monkeypatch):
    """A cache is a store of proposals, never of approvals. If an approve control
    ever writes back here, this fails."""
    _stub(monkeypatch, SW)
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    ck = ai_edge._cache_key(EN, "sw", "gemini-test")
    ai_edge._cache_put(ck, dict(ai_edge._cache_get(ck), approved=True))
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["cached"] is True and r["approved"] is False


# ----------------------------------------------- the edge decides nothing, ever

def test_the_edge_never_writes_to_the_graph(env, monkeypatch):
    _stub(monkeypatch, SW)
    with db.conn() as c:
        before = [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("objects", "impacts", "actions", "hazards", "links")]
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    with db.conn() as c:
        after = [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("objects", "impacts", "actions", "hazards", "links")]
    assert before == after


def test_the_edge_module_never_names_an_engine_table(env):
    """Structural, not behavioural: the edge cannot read an impact or write an
    action because it does not know those tables exist. `geocache` is its only
    contact with the database."""
    src = inspect.getsource(ai_edge)
    body = src.split('"""', 2)[2]                 # skip the module docstring
    for table in ("impacts", "actions", "objects", " links", "hazards"):
        assert table not in body.lower(), f"ai_edge names {table!r}"
    assert "geocache" in body


def test_approved_is_false_in_every_outcome(env, monkeypatch):
    _stub(monkeypatch, "")
    outcomes = [ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})]
    env.setenv("AI_EDGE_LIVE", "0")
    outcomes.append(ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"}))
    env.setenv("AI_EDGE_LIVE", "1")
    env.delenv("GEMINI_API_KEY")
    outcomes.append(ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"}))
    assert all(o["approved"] is False for o in outcomes)


def test_the_prompt_forbids_adding_advice_that_is_not_in_the_source(env, monkeypatch):
    calls = _stub(monkeypatch, SW)
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert "Do not add advice" in ai_edge.SYSTEM
    assert EN in calls[0]["prompt"]
    assert "Swahili" in calls[0]["prompt"]


def test_the_model_string_is_configurable_never_hardcoded(env):
    """Google cut free quotas in Dec 2025 and moved 3.x Pro to paid in Apr 2026.
    A demo that dies on someone else's release schedule is not a demo."""
    env.setenv("GEMINI_MODEL", "gemini-9-flash")
    assert ai_edge._model() == "gemini-9-flash"
    env.delenv("GEMINI_MODEL")
    assert ai_edge._model() == ai_edge.DEFAULT_MODEL


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_request_we_actually_send_is_deterministic_and_authenticated(env, monkeypatch):
    """A flood warning is not a creative task: temperature 0, same input, same
    draft. Checked on the bytes that leave the process, not on the source text."""
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.headers.items()}
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "Usijaribu kuvuka sasa hivi."}]}}]})

    monkeypatch.setattr(ai_edge.urllib.request, "urlopen", fake_urlopen)
    out = ai_edge._call("Translate into Swahili:\n\nDo not try to cross.",
                        "gemini-test", "AQ.test-key")

    assert out == "Usijaribu kuvuka sasa hivi."
    assert seen["body"]["generationConfig"]["temperature"] == 0.0
    assert "Do not add advice" in seen["body"]["system_instruction"]["parts"][0]["text"]
    assert seen["headers"]["x-goog-api-key"] == "AQ.test-key"
    assert "gemini-test:generateContent" in seen["url"]
    # the key rides in a header, never in the URL, so it cannot land in a log
    assert "AQ.test-key" not in seen["url"]
