"""SMTP 邮件发送。"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from .config import MailSettings

log = logging.getLogger(__name__)


def send_mail(ms: MailSettings, *, subject: str, html: str, text: str, attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("民族学学科监测系统", "utf-8")), ms.sender))
    msg["To"] = ", ".join(ms.to)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain", "utf-8"))
    alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(alt)
    for fname, data, mime in attachments or []:
        main, sub = mime.split("/", 1)
        part = MIMEText(data.decode("utf-8"), sub, "utf-8") if main == "text" else None
        if part is None:
            from email.mime.base import MIMEBase
            from email import encoders
            part = MIMEBase(main, sub)
            part.set_payload(data)
            encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", fname))
        msg.attach(part)

    ctx = ssl.create_default_context()
    if ms.use_ssl:
        with smtplib.SMTP_SSL(ms.host, ms.port, context=ctx, timeout=60) as s:
            s.login(ms.user, ms.password)
            s.sendmail(ms.sender, ms.to, msg.as_string())
    else:
        with smtplib.SMTP(ms.host, ms.port, timeout=60) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(ms.user, ms.password)
            s.sendmail(ms.sender, ms.to, msg.as_string())
    log.info("mail sent to %s", ms.to)
