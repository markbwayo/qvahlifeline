"""The AI edge. One function. The only place a model touches LIFELINE.

`ai_edge(task, payload) -> dict`. It translates words that the deterministic core
has already decided. It never sees an impact id, never reads the graph, never
writes to `objects`, `impacts`, `actions` or `messages.csv`, and its output is
never authority. Swap the provider by editing `_call()` and nothing else (07).

What it may translate INTO
--------------------------
Swahili, and nothing else. **Lumasaba is refused, by name, with a raise** - not a
graceful degradation, a refusal. It is the language that actually reaches the last
mile, it is the one every model is worst at, and Bwayo is the only person in the
room who could audit the result. A fluent-looking mistranslation of "do not cross"
is an impact decision taken by a model in the one channel nobody can check
(hard rule 1, D-052). Lumasaba lives in `data/messages.csv`, written by a human.

The asymmetry with `hazards.py`, which is deliberate
----------------------------------------------------
`hazards.scan_live()` RAISES on every feed failure: a dead river gauge that returns
"no hazard" is indistinguishable from a calm river, and that kills people.

`ai_edge()` NEVER raises on a failure: a dead translator returns `edge unavailable`
and the English and Lumasaba text renders exactly as before, because neither passes
through a model. Losing the forecast is losing the warning. Losing the translator is
losing a convenience.

A refusal is not a failure. Asking for Lumasaba raises; the network being down does
not.

What comes back
---------------
Always `status`, always `approved: False`. A successful call returns
`status: "DRAFT"`, and the draft is a proposal for a human, never a message. The
sanity checks below cannot verify a translation - only a Swahili speaker can - so
they check the things a non-speaker CAN check: that the text is not empty, not an
essay, not markdown, carries no URL, and that every proper name we asked to be
preserved actually survived. A name that vanished in translation is surfaced to the
approver, who is the only safeguard that matters.
"""
import hashlib
import json
import os
import sys
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

# A translation of a flood warning is not a creative task.
SYSTEM = (
    "You translate official flood warnings for a district disaster committee in "
    "eastern Uganda. Translate the text exactly. Do not add, omit, soften or "
    "explain anything. Do not add advice that is not in the source. Keep every "
    "proper name (bridges, clinics, villages) exactly as written, untranslated. "
    "Return only the translation, as plain text, with no quotes and no markdown."
)

MAX_EXPANSION = 3.0     # a translation is not an essay
MIN_CONTRACTION = 0.3   # nor a summary


class AIEdgeRefused(Exception):
    """The edge was asked to do something it must never do. Not a failure."""


def _use_live():
    return os.environ.get("USE_LIVE", "0") == "1"


def _api_key():
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def _model():
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _cache_key(text, lang, model):
    h = hashlib.sha256(f"{model}|{lang}|{text}".encode("utf-8")).hexdigest()[:20]
    return f"aiedge:{h}"


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
            "draft": None, "approved": False, "warnings": []}

    if not _use_live():
        return dict(base, status="edge disabled (USE_LIVE=0)")
    key = _api_key()
    if not key:
        return dict(base, status="edge unavailable", reason="no GEMINI_API_KEY")

    model = _model()
    ck = _cache_key(text, lang, model)
    hit = _cache_get(ck)
    if hit:
        return dict(hit, cached=True)

    prompt = f"Translate into {TARGET_LANGS[lang]}:\n\n{text}"
    try:
        draft = _call(prompt, model, key)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200] if hasattr(e, "read") else ""
        return dict(base, status="edge unavailable",
                    reason=f"HTTP {e.code} from {model}: {detail}")
    except Exception as e:                       # noqa: BLE001 - a dead edge is not fatal
        return dict(base, status="edge unavailable",
                    reason=f"{type(e).__name__}: {e}")

    problems, warnings = _sanity(text, draft, preserve)
    if problems:
        return dict(base, status="edge unusable", reason="; ".join(problems),
                    draft=draft)

    out = dict(base, status="DRAFT", draft=draft, model=model, warnings=warnings,
               note="DRAFT - a human must approve this before it is broadcast")
    _cache_put(ck, out)
    return dict(out, cached=False)


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
        print("       python -m app.ai_edge --selftest")
        return 2
    if "--selftest" in argv:
        r = ai_edge("translate", {"text": "Do not try to cross.",
                                  "target_lang": "sw", "preserve": []})
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0 if r["status"] in ("DRAFT", "edge disabled (USE_LIVE=0)") else 1

    from . import messages
    hid = int(argv[0])
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 3
    res = messages.messages_for(hid, "en")
    print(f"live={_use_live()} key={'set' if _api_key() else 'MISSING'} "
          f"model={_model()}")
    for m in res["messages"][:limit]:
        f, _ = messages.facts_for(m["impact_id"])
        d = ai_edge("translate", {
            "text": m["text"], "target_lang": "sw",
            "preserve": [f.get(k) for k in ("settlement", "facility", "crossing")
                         if f.get(k)]})
        print(f"\n[{m['object_id']}] {d['status']}"
              + (f"  ({d.get('reason')})" if d.get("reason") else ""))
        print(f"  EN : {m['text']}")
        print(f"  SW : {d['draft'] or '-'}")
        for w in d.get("warnings", []):
            print(f"  !! {w}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
