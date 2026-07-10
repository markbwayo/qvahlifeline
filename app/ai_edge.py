"""The AI edge. One function. The only place a model touches LIFELINE.

`ai_edge(task, payload) -> dict`. It translates words the deterministic core has
already decided. It never sees an impact id, never reads the graph, never writes
to any engine table, and its output is never authority. Swap the provider by
editing `_call()` and nothing else (07).

What it may translate INTO
--------------------------
Swahili, and nothing else. **Lumasaba is refused, by name, with a raise** - not a
graceful degradation, a refusal. It is the language that actually reaches the last
mile, it is the one every model is worst at, and Bwayo is the only person in the
room who could audit the result. A fluent-looking mistranslation of "do not cross"
is an impact decision taken by a model in the one channel nobody can check
(hard rule 1, D-052). Lumasaba lives in `data/messages.csv`, written by a human.

What it may be TOLD (D-059)
---------------------------
`text`, `target_lang`, `preserve`, and nothing else. An unknown payload key raises.
The check exists so that a later "pass the impact id through, so we can log it"
cannot quietly put a graph identifier into a prompt: hard rule 1 is enforced by the
signature, not by a promise. This module imports `db` for its draft cache and
nothing else from this package, and a test parses this file to prove it.

Two switches, because there are two different guarantees (D-058)
----------------------------------------------------------------
`USE_LIVE` gates the deterministic core - the river feed, the scan, the trigger. It
exists because a dead gauge that returns "no hazard" is indistinguishable from a
calm river, and that kills people. `scan_live()` therefore RAISES on every feed
failure.

`AI_EDGE_LIVE` (default `0`) gates this module, and only this module. A dead edge
returns `edge unavailable`; the English and the Lumasaba text render exactly as
before, because neither ever passes through a model. Losing the forecast is losing
the warning. Losing the translator is losing a convenience. The edge is safe by
construction - which is the property `USE_LIVE` was invented to guarantee by fiat -
so it does not need that switch, and it does need its own. Demo day runs
`USE_LIVE=0, AI_EDGE_LIVE=1`: the flood comes from the graph, the Swahili from the
model.

A refusal is not a failure. Asking for Lumasaba raises; the network being down does
not.

Retrying once, and only where a retry means something (D-057)
--------------------------------------------------------------
429 and 503 mean the request was well formed and the server declined to answer NOW.
The free tier is about ten requests a minute against seventy-two broadcasts, so a
429 is a matter of when, and a live 503 was observed on `gemini-2.5-flash` during
Session 22. One two-second pause, one more attempt.

400, 401, 403 and 404 mean the request will never succeed. Retrying burns quota,
doubles the latency of a certain failure, and delays the only diagnostic that
matters: a rotated key that never reached `.env` arrives as a 403, and the presenter
must see it in one second, not twenty-two. A timeout is not retried either - a 429
is a prompt response, a hang is not, and a hang offers no evidence that a second
attempt would return. The worst case is therefore `2 x TIMEOUT_S + RETRY_PAUSE_S`
= 42 s, reached only if a slow server answers 429 twice; the realistic bound is one
round trip plus two seconds.

What comes back
---------------
Always `status`, always `approved: False`, always `retried`. A successful call
returns `status: "DRAFT"`, and the draft is a proposal for a human, never a message.
The sanity checks below cannot verify a translation - only a Swahili speaker can -
so they check the things a non-speaker CAN check: that the text is not empty, not an
essay, not markdown, carries no URL, and that every proper name we asked to be
preserved actually survived. A name that vanished in translation is surfaced to the
approver, who is the only safeguard that matters.

`status: "edge unusable"` still carries the rejected `draft`, so an operator can see
what came back and judge whether the check was too strict. A caller must render it
as REJECTED. Only `status == "DRAFT"` is a draft.

Serving a draft is not making one (D-060)
------------------------------------------
The order is `gate -> cache -> key -> provider`. A key is required to MAKE a draft,
never to SERVE one, and the cache key does not contain it. Before D-060 an empty key
blocked a cached draft while a garbage key sailed straight past it - one of those two
had to be wrong. If `.env` fails to load on demo morning, seventy-two rehearsed
Swahili drafts still render, each flagged `cached: True`. The gate stays in front of
everything: `AI_EDGE_LIVE=0` means do not use the edge, and a cache is part of the
edge.

`cached_draft(text, lang)` is the read-only door for a page render. It never calls
the provider, never writes, and returns `None` on a miss. A round trip to Google was
measured at 11.3 s on the pilot VPS (a degraded IPv6 route, since fixed), and the
free tier is ~10 RPM against 72 broadcasts. A page that calls the provider in its
render path is not a page. `cached_draft` is ungated on purpose: `AI_EDGE_LIVE`
governs whether we may speak to a model, and reading a draft we already have does
not speak to anyone.

Any live probe of this module that reuses a previously translated string is
unfalsifiable, because it never reaches the provider. `--selftest` therefore takes
its own text.
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

from . import db

# Free tier, no card. Google may use free-tier inputs and outputs to improve their
# products: the payload here is public warning text naming villages and bridges, and
# carries no personal data. Model is env-configurable on purpose - Google moved the
# 3.x Pro models to paid-only in April 2026 and cut free quotas in December 2025.
# A hardcoded model string is a demo that dies on someone else's release schedule.
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT_S = 20

# The edge may translate INTO these. Never `lum` (D-052). Never `en` (the source).
TARGET_LANGS = {"sw": "Swahili"}
TASKS = {"translate"}

# D-059. Everything the edge is allowed to be told. Not a subset it reads and a
# remainder it ignores - a closed set, and an unknown key is a refusal.
PAYLOAD_KEYS = frozenset({"text", "target_lang", "preserve"})

# D-057. `come back` versus `you are wrong`. Retry the first, never the second.
RETRY_STATUS = frozenset({429, 503})
RETRY_PAUSE_S = 2.0
MAX_ATTEMPTS = 2                       # one attempt, one retry. Never a loop.

# D-058. This module's own gate. `USE_LIVE` guards the deterministic core and is
# not read here: the two switches guard different failures.
EDGE_LIVE_VAR = "AI_EDGE_LIVE"

DISABLED = f"edge disabled ({EDGE_LIVE_VAR}=0)"
UNAVAILABLE = "edge unavailable"
UNUSABLE = "edge unusable"

# A translation of a flood warning is not a creative task.
SYSTEM = (
    "You translate official flood warnings for a district disaster committee in "
    "eastern Uganda. Translate the text exactly. Do not add, omit, soften or "
    "explain anything. Do not add advice that is not in the source. Keep every "
    "proper name (bridges, clinics, villages) exactly as written, untranslated. "
    "Return only the translation, as plain text, with no quotes and no markdown."
)

SELFTEST_TEXT = "Do not try to cross."

MAX_EXPANSION = 3.0     # a translation is not an essay
MIN_CONTRACTION = 0.3   # nor a summary


class AIEdgeRefused(Exception):
    """The edge was asked to do something it must never do. Not a failure."""


def _edge_live():
    return os.environ.get(EDGE_LIVE_VAR, "0") == "1"


def _api_key():
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def _model():
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _pause():
    time.sleep(RETRY_PAUSE_S)


def _cache_key(text, lang, model):
    """The instruction is part of the input (D-059). Tune SYSTEM after a rehearsal
    and every cached draft was produced under wording nobody recorded."""
    raw = f"{model}|{lang}|{SYSTEM}|{text}"
    return "aiedge:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _cache_get(key):
    with db.conn() as c:
        row = c.execute("SELECT value_json FROM geocache WHERE key=?", (key,)).fetchone()
    return json.loads(row["value_json"]) if row else None


def _cache_put(key, value):
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO geocache VALUES (?,?,?)",
                  (key, json.dumps(value), db.now()))


def _call(prompt, model, key):
    """The provider. Swapping Gemini for anything else means editing this and
    nothing else (07). urllib only - no dependency for one HTTP POST."""
    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0},
    }).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT.format(model=model), data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        data = json.loads(r.read().decode("utf-8"))
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()


def _http_reason(err, model):
    """Name the model that failed. A 404 on a retired model string must say WHICH
    string, or the fix is a guessing game at 2am."""
    try:
        detail = err.read().decode("utf-8", "replace")[:200]
    except Exception:                            # noqa: BLE001 - a body is a courtesy
        detail = ""
    return f"HTTP {err.code} from {model}: {detail}"


def _sanity(source, draft, preserve):
    """What a non-speaker can check. Not a verification of meaning - there is none,
    which is exactly why the human approves."""
    problems, warnings = [], []
    if not draft:
        problems.append("empty draft")
    elif "```" in draft or "http://" in draft or "https://" in draft:
        problems.append("draft contains markdown or a URL")
    elif len(draft) > len(source) * MAX_EXPANSION:
        problems.append("draft is far longer than the source; not a translation")
    elif len(draft) < len(source) * MIN_CONTRACTION:
        problems.append("draft is far shorter than the source; content was dropped")
    for name in preserve or ():
        if name and name not in draft:
            warnings.append(f"proper name not preserved: {name!r}")
    return problems, warnings


def ai_edge(task, payload):
    """The single adapter. Returns a dict; raises only on a forbidden request."""
    if task not in TASKS:
        raise AIEdgeRefused(f"unknown task {task!r}; the edge does {sorted(TASKS)}")

    unknown = sorted(set(payload) - PAYLOAD_KEYS)
    if unknown:
        raise AIEdgeRefused(
            f"payload key(s) {unknown} are not permitted; the edge is told "
            f"{sorted(PAYLOAD_KEYS)} and nothing else. It must never be handed a "
            f"graph identifier (D-059, hard rule 1).")

    text = (payload.get("text") or "").strip()
    lang = (payload.get("target_lang") or "").strip()
    preserve = payload.get("preserve") or []

    if not text:
        raise AIEdgeRefused("nothing to translate")
    if lang == "lum":
        raise AIEdgeRefused(
            "the edge will never generate Lumasaba (D-052). It reaches the last "
            "mile, no model is good at it, and nobody here can audit the result. "
            "Write it in data/messages.csv.")
    if lang not in TARGET_LANGS:
        raise AIEdgeRefused(
            f"target_lang must be one of {sorted(TARGET_LANGS)}, got {lang!r}")

    base = {"task": task, "target_lang": lang, "source_text": text,
            "draft": None, "approved": False, "warnings": [], "retried": False}

    # D-060. Gate, then cache, then key, then the provider. A key is needed to MAKE
    # a draft, not to SERVE one. The gate is in front of both: `AI_EDGE_LIVE=0`
    # means do not use the edge, and the cache is part of the edge.
    if not _edge_live():
        return dict(base, status=DISABLED)

    model = _model()
    ck = _cache_key(text, lang, model)
    hit = _cache_get(ck)
    if hit:
        return dict(hit, cached=True, approved=False)

    key = _api_key()
    if not key:
        return dict(base, status=UNAVAILABLE, reason="no GEMINI_API_KEY")

    prompt = f"Translate into {TARGET_LANGS[lang]}:\n\n{text}"
    attempt, retried = 0, False
    while True:
        attempt += 1
        try:
            draft = _call(prompt, model, key)
            break
        except urllib.error.HTTPError as e:
            # D-057. A 429 or a 503 is the server saying `try again`. A 400 or a
            # 403 is the server saying `you are wrong`, and retrying a wrong
            # request is a way of not reading the error.
            if e.code in RETRY_STATUS and attempt < MAX_ATTEMPTS:
                retried = True
                _pause()
                continue
            return dict(base, status=UNAVAILABLE, reason=_http_reason(e, model),
                        retried=retried)
        except Exception as e:                   # noqa: BLE001 - a dead edge is not fatal
            # A hang, a DNS failure, a refused connection. Not retried: there is no
            # evidence a second attempt would return, and 42 s of a two-minute demo
            # is a worse outcome than a rendered English warning with no Swahili.
            return dict(base, status=UNAVAILABLE, reason=f"{type(e).__name__}: {e}",
                        retried=retried)

    problems, warnings = _sanity(text, draft, preserve)
    if problems:
        return dict(base, status=UNUSABLE, reason="; ".join(problems),
                    draft=draft, retried=retried)

    out = dict(base, status="DRAFT", draft=draft, model=model, warnings=warnings,
               retried=retried,
               note="DRAFT - a human must approve this before it is broadcast")
    _cache_put(ck, out)
    return dict(out, cached=False)


def cached_draft(text, lang="sw"):
    """A draft we already have, or None. The read-only door (D-060).

    Never calls the provider, never writes, never blocks on a network. This is the
    only function a page render may call: a round trip is seconds, the free tier is
    ten requests a minute, and sixty-two villages is not a page load.

    Ungated. `AI_EDGE_LIVE` governs whether we may speak to a model; reading a draft
    that already exists speaks to nobody. `approved` is forced False on the way out -
    the cache stores proposals, never approvals.
    """
    text = (text or "").strip()
    lang = (lang or "").strip()
    if lang == "lum":
        raise AIEdgeRefused(
            "the edge will never generate Lumasaba (D-052), so it can never have "
            "cached one. Write it in data/messages.csv.")
    if lang not in TARGET_LANGS:
        raise AIEdgeRefused(
            f"target_lang must be one of {sorted(TARGET_LANGS)}, got {lang!r}")
    if not text:
        return None
    hit = _cache_get(_cache_key(text, lang, _model()))
    return dict(hit, cached=True, approved=False) if hit else None


def draft_swahili(message):
    """Convenience for a rendered message from `messages.render()`.

    Proper names are pulled from the facts the ENGINE produced, so the check that
    they survived translation is a check against the graph, not against the prose.
    """
    preserve = [v for k, v in (message.get("facts") or {}).items()
                if k in ("settlement", "facility", "crossing") and v]
    return ai_edge("translate", {"text": message["text"], "target_lang": "sw",
                                 "preserve": preserve})


def _cli(argv):
    if not argv:
        print("usage: python -m app.ai_edge <hazard_id> [--limit N]")
        print("       python -m app.ai_edge --selftest [text]")
        return 2
    if "--selftest" in argv:
        # D-060. A fixed string cannot reach the provider once it is cached, so a
        # selftest that never varies its text can never fail. Pass your own.
        i = argv.index("--selftest")
        text = (argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("-")
                else SELFTEST_TEXT)
        r = ai_edge("translate", {"text": text, "target_lang": "sw", "preserve": []})
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0 if r["status"] in ("DRAFT", DISABLED) else 1

    from . import messages
    hid = int(argv[0])
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 3
    res = messages.messages_for(hid, "en")
    print(f"{EDGE_LIVE_VAR}={_edge_live()} key={'set' if _api_key() else 'MISSING'} "
          f"model={_model()}")
    for m in res["messages"][:limit]:
        f, _ = messages.facts_for(m["impact_id"])
        d = ai_edge("translate", {
            "text": m["text"], "target_lang": "sw",
            "preserve": [f.get(k) for k in ("settlement", "facility", "crossing")
                         if f.get(k)]})
        print(f"\n[{m['object_id']}] {d['status']}"
              + ("  (retried)" if d.get("retried") else "")
              + (f"  ({d.get('reason')})" if d.get("reason") else ""))
        print(f"  EN : {m['text']}")
        print(f"  SW : {d['draft'] if d['status'] == 'DRAFT' else '-'}")
        for w in d.get("warnings", []):
            print(f"  !! {w}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
