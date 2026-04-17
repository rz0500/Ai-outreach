"""
scheduler.py — Standalone scheduler process
============================================
Run the background scheduler without starting the Flask web server.

Usage:
    python scheduler.py

This lets you run the web process and the scheduler as separate processes,
e.g. with a process manager (Procfile, systemd, supervisor):

    web:        python web_app.py --no-scheduler
    scheduler:  python scheduler.py

Environment:
    Same .env as web_app.py — all settings (SMTP, API keys, etc.) are shared.
"""

import logging
import database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
)

if __name__ == "__main__":
    logging.info("Initialising database…")
    database.initialize_database()

    logging.info("Starting Antigravity background scheduler (standalone mode).")
    logging.info("Web server is NOT started. Run web_app.py separately.")

    # Import after DB init so all modules see a ready database
    from web_app import _background_scheduler
    _background_scheduler()
