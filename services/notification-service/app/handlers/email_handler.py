import os
import structlog

log = structlog.get_logger()

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")


def send_contact_email(seller_id: str, buyer_id: str, item_id: int,
                       subject: str, message: str) -> bool:
    """
    Sends email notification to seller when a buyer contacts them.
    In dev: logs the email payload instead of actually sending.
    In prod: configure SMTP_HOST/USER/PASS env vars.
    """
    if not SMTP_HOST:
        log.info("email_simulated",
                 to_seller=seller_id, from_buyer=buyer_id,
                 item=item_id, subject=subject)
        return True

    try:
        import smtplib
        from email.mime.text import MIMEText
        body = f"Item: {item_id}\nFrom buyer: {buyer_id}\n\n{subject}\n\n{message}"
        msg = MIMEText(body)
        msg["Subject"] = f"[ElectroHub] New message: {subject}"
        msg["From"] = SMTP_USER
        msg["To"] = seller_id  # in production, look up email from user-service
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        log.info("email_sent", seller=seller_id, item=item_id)
        return True
    except Exception as exc:
        log.error("email_failed", error=str(exc))
        return False
