# Two processes are required. Run both on your platform.
#
# Memory note: gunicorn --workers 2 forks 2 worker processes. Each worker loads
# the full Flask app into memory. Budget ~2× your per-worker RAM usage. The
# scheduler process runs in a separate dyno/container and must also be started.
#
# Render: add both as separate services (Web Service + Background Worker).
# Each needs the same environment variables and access to the same persistent disk.

web:       gunicorn web_app:app --workers 2 --bind 0.0.0.0:$PORT
scheduler: python scheduler.py
