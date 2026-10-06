"""Daily autopilot keeps looking in batches until the queue is full, within a candidate budget."""

import os
import unittest
from unittest.mock import patch

import web_app


def _fake_discover(target, **kwargs):
    return [{"company": f"Co{i}"} for i in range(target)]


class TestAutopilotBudget(unittest.TestCase):
    def _run(self, backlog, budget, pipeline_effect=None):
        queue = {"n": backlog}

        def pipeline(prospect, **kw):
            if pipeline_effect and pipeline_effect(prospect):
                queue["n"] += 1

        with patch.dict(os.environ, {"AUTOPILOT_MAX_CANDIDATES": str(budget)}), \
             patch.object(web_app.database, "get_client", return_value={"campaign_paused": 0, "daily_send_limit": 0}), \
             patch.object(web_app.warmup_engine, "get_daily_limit", return_value=10), \
             patch.object(web_app, "_queued_initial_sends", side_effect=lambda db: queue["n"]), \
             patch("job_leads.discover_job_leads", side_effect=_fake_discover), \
             patch("lead_discovery.discover_new_leads", return_value=[]), \
             patch.object(web_app, "_run_pipeline_for_db_prospect", side_effect=pipeline) as run:
            processed = web_app._run_daily_autopilot()
        return processed, run.call_count

    def test_keeps_looking_until_budget_when_few_leads_survive(self):
        processed, calls = self._run(backlog=0, budget=40)
        self.assertEqual((processed, calls), (40, 40))

    def test_stops_as_soon_as_the_queue_is_full(self):
        # queue target = 2 x cap(10) = 20; every candidate yields a queued email
        processed, _ = self._run(backlog=0, budget=150, pipeline_effect=lambda p: True)
        self.assertEqual(processed, 30)    # batches of 15 until backlog >= 20

    def test_full_queue_does_nothing(self):
        self.assertEqual(self._run(backlog=25, budget=150)[0], 0)


if __name__ == "__main__":
    unittest.main()
