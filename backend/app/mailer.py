"""Sends email through any SMTP server (Gmail with an app password, Brevo, ...).

Settings come from .env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM.
One SmtpMailer keeps one connection open for many emails:
    with SmtpMailer() as mailer:
        mailer.send(message)
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Optional

from app import config


def is_configured() -> bool:
    return bool(config.SMTP_HOST and config.MAIL_FROM)


def build_message(to: str, subject: str, text: str, html_body: str,
                  unsubscribe_url: Optional[str] = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((config.MAIL_FROM_NAME, config.MAIL_FROM))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=config.MAIL_FROM.rsplit("@", 1)[-1] or None)
    if unsubscribe_url:
        # lets Gmail / Outlook show their own "Unsubscribe" button (one click, RFC 8058)
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    return msg


class SmtpMailer:
    def __enter__(self) -> "SmtpMailer":
        context = ssl.create_default_context()
        if config.SMTP_PORT == 465:
            self.smtp = smtplib.SMTP_SSL(config.SMTP_HOST, 465, context=context, timeout=30)
        else:
            self.smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
            self.smtp.starttls(context=context)
        if config.SMTP_USER:
            self.smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        return self

    def send(self, msg: EmailMessage) -> None:
        self.smtp.send_message(msg)

    def __exit__(self, *exc) -> None:
        try:
            self.smtp.quit()
        except smtplib.SMTPException:
            pass
