"""Broadcast approvals. A human's signature on a draft, and nowhere near the model.

The AI edge caches PROPOSALS. This module records DECISIONS. They are two different
things and they live in two different places on purpose (D-060): `cached_draft`
forces `approved: False` on the way out, because a cache is a store of what a model
said, never of what a person signed. An approve control that wrote back into that
cache row would collapse the one wall the whole AI-edge doctrine rests on - the wall
between what was proposed and what was authorised.

So approval is its own table, keyed to the exact bytes that were approved:
`(impact_id, lang, text_hash)`. The hash is over the SWAHILI DRAFT TEXT, not the
English source and not the impact id alone. A draft re-translated after the system
prompt changed (D-059) has a different hash, so an old approval does not silently
bless new words. Re-approving is the committee's job, and the schema makes them do
it rather than letting a stale signature ride.

Nothing here calls a model, and nothing here decides an impact. It writes one row
when a human clicks approve, and reads it back so the panel can show a badge. That
is the entire surface.
"""
import hashlib

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    impact_id   INTEGER NOT NULL,
    lang        TEXT    NOT NULL,
    text_hash   TEXT    NOT NULL,
    approved_by TEXT    NOT NULL,
    approved_at TEXT    NOT NULL,
    PRIMARY KEY (impact_id, lang, text_hash)
);
"""


_ensured = set()


def _ready():
    """Idempotent, self-healing, like db.conn() (D-037). A migration that depends
    on someone remembering to run it will be missed by a script, a cron, or a
    fresh deployment. Committed explicitly so it survives however the caller's
    connection context manager behaves, and memoised per DB path so it is cheap."""
    if db.DB_PATH in _ensured:
        return
    with db.conn() as c:
        c.executescript(SCHEMA)
        c.commit()
    _ensured.add(db.DB_PATH)


def text_hash(text):
    """The signature is over the bytes a human read, so it moves when they move."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:20]


def approve(impact_id, lang, text, approved_by="operator"):
    """Record that a human signed this exact draft. Idempotent: approving the same
    bytes twice is one row, not two."""
    _ready()
    h = text_hash(text)
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO approvals VALUES (?,?,?,?,?)",
                  (impact_id, lang, h, approved_by, db.now()))
    return {"impact_id": impact_id, "lang": lang, "text_hash": h,
            "approved_by": approved_by}


def is_approved(impact_id, lang, text):
    """Was THIS text approved for this impact and language? A different draft - a
    re-translation under a changed prompt - has a different hash and is not."""
    _ready()
    h = text_hash(text)
    with db.conn() as c:
        row = c.execute(
            "SELECT approved_by, approved_at FROM approvals WHERE impact_id=? AND "
            "lang=? AND text_hash=?", (impact_id, lang, h)).fetchone()
    return dict(row) if row else None


def approved_for(hazard_id, lang):
    """Every approval standing for this hazard's impacts in this language, keyed by
    impact id. The panel reads this once and badges each broadcast."""
    _ready()
    with db.conn() as c:
        rows = c.execute(
            "SELECT a.impact_id, a.text_hash, a.approved_by, a.approved_at "
            "FROM approvals a JOIN impacts i ON i.id=a.impact_id "
            "WHERE i.hazard_id=? AND a.lang=?", (hazard_id, lang)).fetchall()
    return {r["impact_id"]: dict(r) for r in rows}
