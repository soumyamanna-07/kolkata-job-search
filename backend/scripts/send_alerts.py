"""Email each user the NEW jobs for their saved alerts.

Run from the backend/ folder, after update_jobs:
    python -m scripts.send_alerts --dry-run     # show who would get what, send and change nothing
    python -m scripts.send_alerts               # send
Safe to run many times: an alert is only sent when it is due (about 24 hours or
7 days after the last one). Alerts with no new jobs get no email.
"""
import argparse
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import psycopg
from psycopg.rows import dict_row

from app import alerts, config, mailer

DUE_SQL = """
    select a.id, a.user_id::text as user_id, a.name, a.filters, a.use_cv_match, a.frequency,
           a.last_sent_at, a.created_at, u.email, p.full_name
    from public.job_alerts a
    join public.profiles p on p.id = a.user_id
    join auth.users u on u.id = a.user_id
    where a.is_active and a.channel = 'email' and a.frequency in ('daily', 'weekly')
      and not p.is_blocked and u.email is not null
    order by a.last_sent_at nulls first, a.created_at
"""


@dataclass
class Stats:
    checked: int = 0
    not_due: int = 0
    no_new_jobs: int = 0
    sent: int = 0
    failed: int = 0
    left_for_next_run: int = 0


def run(conn: psycopg.Connection, make_mailer: Callable, now: datetime, dry_run: bool = False,
        max_emails: int = 400, log: Callable[[str], None] = print) -> Stats:
    stats = Stats()
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(DUE_SQL).fetchall()
    with ExitStack() as stack:
        sender = None
        for a in rows:
            stats.checked += 1
            if not alerts.is_due(a["frequency"], a["last_sent_at"], now):
                stats.not_due += 1
                continue
            if stats.sent >= max_emails:
                stats.left_for_next_run += 1
                continue
            since = alerts.since_for(a["frequency"], a["last_sent_at"], a["created_at"])
            jobs, total = alerts.find_new_jobs(conn, a["user_id"], a["filters"], a["use_cv_match"], since)
            if not jobs:
                stats.no_new_jobs += 1
                if not dry_run:          # nothing new: next email starts counting from now
                    conn.execute("update public.job_alerts set last_sent_at = %s where id = %s", (now, a["id"]))
                continue
            email = alerts.build_email(a["full_name"], a["name"], jobs, total, a["id"])
            if dry_run:
                log(f"  would send to {a['email']}: {email.subject}")
                stats.sent += 1
                continue
            try:
                if sender is None:
                    sender = stack.enter_context(make_mailer())
                sender.send(mailer.build_message(a["email"], email.subject, email.text, email.html,
                                                 email.unsubscribe_url))
            except Exception as exc:     # one bad address must not stop everyone else's emails
                stats.failed += 1
                log(f"  FAILED alert {a['id']}: {type(exc).__name__}: {exc}")
                continue
            conn.execute("update public.job_alerts set last_sent_at = %s where id = %s", (now, a["id"]))
            stats.sent += 1
            log(f"  sent: {email.subject}")
    return stats


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Email new jobs for saved job alerts.")
    parser.add_argument("--dry-run", action="store_true", help="show what would be sent; send and change nothing")
    parser.add_argument("--max-emails", type=int, default=config.ALERT_EMAILS_PER_RUN)
    args = parser.parse_args(argv)

    if not config.DATABASE_URL:
        print("DATABASE_URL is not set in .env", file=sys.stderr)
        return 1
    if not args.dry_run:
        missing = [name for name in ("SMTP_HOST", "MAIL_FROM", "ALERTS_SECRET") if not getattr(config, name)]
        if missing:
            print(f"Cannot send emails: set {', '.join(missing)} in .env (or use --dry-run).", file=sys.stderr)
            return 1
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        stats = run(conn, mailer.SmtpMailer, datetime.now(timezone.utc), args.dry_run, args.max_emails)
    label = "would send" if args.dry_run else "sent"
    print(f"Alerts checked {stats.checked}: {label} {stats.sent}, no new jobs {stats.no_new_jobs}, "
          f"not due yet {stats.not_due}, failed {stats.failed}, left for next run {stats.left_for_next_run}")
    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
