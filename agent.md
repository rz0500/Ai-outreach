# Agent Instructions

Read this at the start of every session. Update after meaningful changes.

---

## Recently Completed

### Session 2 (hardening pass)
All 10 build tasks: background scheduler, booking detection, settings UI, prospect CRUD, email validation, analytics panel, bulk CSV import, SendGrid routing, LinkedIn dry-run wiring, settings.py expansion.

### Session 3 (operator UX)
- `delete_prospect()` cascades to `prospect_research`
- `_smtp_send_email` rename so all sends go through `_route_send_email()`
- `POST /api/prospects` manual Add Lead endpoint
- Add Lead inline form in dashboard
- Reply draft editable textarea before approve-and-send
- `POST /api/prospects/<id>/enrol` sequence enrolment endpoint
- Enrol button per prospect in pipeline table
- Basic Auth on `/settings` using `SETTINGS_USER` / `SETTINGS_PASSWORD`
- Scheduler crash resilience with `consecutive_errors`, `paused`, and `/api/monitor-status`

### Session 4 (scheduler control)
- `POST /api/monitor-reset` clears `paused=False`, `consecutive_errors=0`, and `last_inbox_error=None`
- Dashboard header now shows `Resume Inbox Polling` only while the monitor is paused
- Pipeline table now shows a `Sequence` column with `Day N` or `Not enrolled` based on `sequence_enrollments.enrolled_at`

### Session 5 (test cleanup)
- Restored shared `OPT_OUT_LINE` compatibility in `outreach.py` so compliance and legacy sequence paths agree again
- Updated reply workflow tests for `_route_send_email()` and thread-header behavior
- Realigned email reasoning and inbox monitor tests with the current operator-style email flow
- Full `python -m unittest discover` suite is passing again

### Session 6 (live inbox hardening)
- Fixed IMAP search query in `inbox_monitor.py` from `UNREAD` to `UNSEEN` for Gmail compatibility
- Added tolerant MIME decoding for `unknown-8bit` / unknown charsets
- Added `IMAP_MAX_MESSAGES_PER_POLL` cap (default `25`) so one large unread backlog does not stall a poll cycle
- Live Gmail smoke test now connects, authenticates, selects inbox, and searches successfully

---

## Next Session - Planned Tasks

### P1 - Test suite
1. **Update `test_reply_workflow.py`**
   - Add test for the `booked` classification path in `_handle_classified_reply`
   - Check prospect status becomes `booked` and enrollment becomes `completed`

2. **Add `test_api_endpoints.py`** using Flask test client
   - `POST /api/prospects`
   - `PATCH /api/prospects/<id>`
   - `DELETE /api/prospects/<id>` with cascade check
   - `POST /api/prospects/<id>/enrol`
   - `GET /api/analytics`
   - `POST /api/import-csv`

3. **Add `test_email_validation.py`**
   - Valid address passes
   - Bad syntax rejected
   - Unresolvable domain rejected

### P2 - Polish
4. **`/api/find-and-fire` progress streaming**
   - It currently blocks until all businesses are processed
   - Switch to SSE or job ID plus polling

5. **Inbox monitor follow-up**
   - Consider more defensive decoding around odd real-world messages
   - Consider reducing backlog by using a narrower search window or a smaller poll cap

### P3 - Production
5. **Gunicorn startup script**
   - Separate worker for `_background_scheduler`

6. **`.env.example` audit**
   - Ensure all new config keys are documented

---

## Active Constraints

- `LINKEDIN_DRY_RUN=true` by default
- `USE_SENDGRID=true` routes through SendGrid and still lacks attachment/thread-header support
- Scheduler only starts from `python web_app.py`
- All sends in `web_app.py` must go through `_route_send_email()`
- `/settings` is Basic Auth protected
