"""The AI edge. The only place a model speaks, and the smallest surface in the repo.

Two behaviours are opposites on purpose, and both are tested:

  * a REFUSAL raises (Lumasaba, an unknown language, an unknown task);
  * a FAILURE returns (no key, dead network, HTTP error, garbage response).

`hazards.scan_live()` is the mirror image: every feed failure raises, because a
dead gauge reporting "no hazard" is indistinguishable from a calm river. Losing
the forecast loses the warning. Losing the translator loses a convenience.
"""
import inspect
import json
import urllib.error

import pytest

from app import ai_edge, db

EN = "Manafwa Bridge may become impassable in this flood. Do not try to cross."


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dbfile = str(tmp_path / "t.db")
    monkeypatch.setattr(db, "DB_PATH", dbfile)
    db._schema_ready.discard(dbfile)
    db.init()
    monkeypatch.setenv("USE_LIVE", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    yield monkeypatch
    db._schema_ready.discard(dbfile)


def _stub(monkeypatch, reply):
    calls = []

    def fake(prompt, model, key):
        calls.append({"prompt": prompt, "model": model, "key": key})
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(ai_edge, "_call", fake)
    return calls


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


# ---------------------------------------------- failures: these RETURN, never raise

def test_a_disabled_edge_returns_rather_than_raises(env):
    env.setenv("USE_LIVE", "0")
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge disabled (USE_LIVE=0)"
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
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    monkeypatch.setattr(err, "read", lambda: b"model not found", raising=False)
    _stub(monkeypatch, err)
    r = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert r["status"] == "edge unavailable" and "gemini-test" in r["reason"]


# --------------------------------------------------- what a non-speaker can check

def test_a_good_translation_comes_back_as_a_draft_never_as_a_message(env, monkeypatch):
    _stub(monkeypatch, "Daraja la Manafwa linaweza kufungwa. Usijaribu kuvuka.")
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


# ------------------------------------------------------------------- the cache

def test_a_second_identical_request_does_not_touch_the_provider(env, monkeypatch):
    """10 requests per minute on the free tier, and 72 broadcasts on the real
    graph. Caching is not an optimisation."""
    calls = _stub(monkeypatch, "Daraja la Manafwa linaweza kufungwa. Usijaribu kuvuka.")
    a = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    b = ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 1
    assert a["draft"] == b["draft"] and b["cached"] is True


def test_a_bad_draft_is_never_cached(env, monkeypatch):
    calls = _stub(monkeypatch, "")
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 2


def test_changing_the_model_invalidates_the_cache(env, monkeypatch):
    calls = _stub(monkeypatch, "Daraja la Manafwa linaweza kufungwa. Usijaribu kuvuka.")
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    env.setenv("GEMINI_MODEL", "gemini-other")
    ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"})
    assert len(calls) == 2


# ----------------------------------------------- the edge decides nothing, ever

def test_the_edge_never_writes_to_the_graph(env, monkeypatch):
    _stub(monkeypatch, "Daraja la Manafwa linaweza kufungwa. Usijaribu kuvuka.")
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
    env.setenv("USE_LIVE", "0")
    outcomes.append(ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"}))
    env.setenv("USE_LIVE", "1")
    env.delenv("GEMINI_API_KEY")
    outcomes.append(ai_edge.ai_edge("translate", {"text": EN, "target_lang": "sw"}))
    assert all(o["approved"] is False for o in outcomes)


def test_the_prompt_forbids_adding_advice_that_is_not_in_the_source(env, monkeypatch):
    calls = _stub(monkeypatch, "Daraja la Manafwa linaweza kufungwa. Usijaribu kuvuka.")
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
                        "gemini-test", "AIza-test")

    assert out == "Usijaribu kuvuka sasa hivi."
    assert seen["body"]["generationConfig"]["temperature"] == 0.0
    assert "Do not add advice" in seen["body"]["system_instruction"]["parts"][0]["text"]
    assert seen["headers"]["x-goog-api-key"] == "AIza-test"
    assert "gemini-test:generateContent" in seen["url"]
    # the key rides in a header, never in the URL, so it cannot land in a log
    assert "AIza-test" not in seen["url"]
