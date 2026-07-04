"""Action generation: playbook lookup only. The committee owns the playbook CSV;
the tool fires it. No action without a matching impact (invariant 4)."""
import csv
import os

from . import db

_PLAYBOOK = os.path.join(os.path.dirname(__file__), "..", "data", "playbook.csv")


def load_playbook():
    rules = {}
    with open(_PLAYBOOK, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["object_type"], row["state"], row["hazard_kind"])
            rules.setdefault(key, []).append(row)
    return rules


def generate(hazard_id: int) -> int:
    """Create actions for every impact of this hazard that matches the playbook."""
    rules = load_playbook()
    created = 0
    with db.conn() as c:
        hz = c.execute("SELECT kind FROM hazards WHERE id=?", (hazard_id,)).fetchone()
        rows = c.execute(
            "SELECT i.id, i.state, o.type FROM impacts i JOIN objects o "
            "ON o.id = i.object_id WHERE i.hazard_id=?", (hazard_id,)).fetchall()
        for r in rows:
            for rule in rules.get((r["type"], r["state"], hz["kind"]), []):
                c.execute(
                    "INSERT INTO actions (impact_id, action_text, owner_role, "
                    "lead_time_hrs) VALUES (?,?,?,?)",
                    (r["id"], rule["action_text"], rule["owner_role"],
                     int(rule["lead_time_hrs"])))
                created += 1
    return created
