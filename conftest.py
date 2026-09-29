"""
Global test guard: no test may open a real SMTP connection.

The onboarding-route tests used to send real "New lead" emails from the live
mailbox on every full run. With this fixture a test that reaches the SMTP layer
gets a refused connection (mailer.send_email reports it as a failed send), so
nothing leaves the machine. Tests that exercise SMTP patch smtplib themselves,
which overrides this guard for the duration of that test.
"""

import smtplib

import pytest


class _BlockedSMTP:
    def __init__(self, *args, **kwargs):
        raise ConnectionRefusedError("real SMTP is blocked while running tests")


@pytest.fixture(autouse=True)
def _block_real_smtp(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _BlockedSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _BlockedSMTP)
