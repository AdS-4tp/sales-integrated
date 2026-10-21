"""Mailers. v0 has exactly one: a dry-run outbox. Nothing can leave the machine.

A real SMTP/Gmail/Outlook mailer will implement the same interface and set
``can_send = True``, which switches the send guard to strict mode.
"""
from __future__ import annotations

import sqlite3


class DryRunMailer:
    kind = "dry_run"
    can_send = False

    def send(self, conn: sqlite3.Connection, *, decision_id: int, to_email: str,
             subject: str, body: str, at: str) -> None:
        conn.execute(
            "INSERT INTO outbox(decision_id,to_email,subject,body,at) VALUES(?,?,?,?,?)",
            (decision_id, to_email, subject, body, at),
        )
        conn.commit()
