"""One timeline of what the agent did alone, what it proposed, what it holds and what it refused (read-only, built from the Passport autonomy log,
the session log and the pending drafts; nothing here changes state)."""
from __future__ import annotations

_ALONE = {"rate_target_conversion": "converted at your rate target", "recurring_bill_paid": "paid a recurring bill within your Tier-1 limits"}
_HELD = {"rate_target_needs_approval": "held a rate-target conversion for your approval", "recurring_bill_held": "held a recurring bill for your signature"}
_REFUSED = {"rate_target_blocked": "blocked a rate-target conversion"}


def timeline(S, session_log: list | None = None) -> dict:
    w = S.world
    alone, held, refused, proposed = [], [], [], []
    for e in w.passport.autonomy_log:
        k = e.get("kind", "")
        row = {"day": e.get("day"), "kind": k, "what": _ALONE.get(k) or _HELD.get(k) or _REFUSED.get(k) or k.replace("_", " "), "rule": e.get("rule")}
        (alone if k in _ALONE else held if k in _HELD else refused if k in _REFUSED else proposed).append(row)
    for pid, item in S.pending.items():
        dr = (item.get("outcome") or {}).get("draft") or {}
        held.append({"day": w.today.isoformat(), "kind": "draft_waiting", "what": f"draft {pid} waiting for your device-key signature",
                     "amount": dr.get("amount"), "payee": dr.get("payee_name")})
    for intent, status, text in (session_log or []):
        row = {"kind": intent, "what": text}
        (refused if status in ("refused", "rejected") else proposed).append(row)
    return {"acted_alone": alone, "proposed_or_approved": proposed, "held": held, "refused": refused}


def summary(S, session_log: list | None, lang: str = "en") -> str:
    t = timeline(S, session_log)
    n = {k: len(v) for k, v in t.items()}
    if not any(n.values()):
        return ("我还没有替您做过任何事：没有自动执行、没有提议、没有扣留，也没有拒绝。" if lang == "zh"
                else "I haven't done anything for you yet: nothing automatic, proposed, held or refused.")
    def part(rows, zh, en):
        return f"{zh if lang == 'zh' else en}（{len(rows)}）：" + "；".join(r["what"] for r in rows[-3:]) + "。" if rows else ""
    parts = [part(t["acted_alone"], "我自己完成的", "Done on my own"), part(t["proposed_or_approved"], "提议/经您批准的", "Proposed or approved"),
             part(t["held"], "扣留等您的", "Held for you"), part(t["refused"], "我拒绝的", "Refused")]
    tail = " 每一笔自动操作都在审计链里，且受您设定的上限约束。" if lang == "zh" else " Every automatic action is in the audit chain and stays inside your Tier-1 limits."
    return " ".join(p for p in parts if p) + tail
