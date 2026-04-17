import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-google-maps-key")

import database
import web_app


def _make_test_db():
    db = tempfile.mktemp(suffix=".db")
    database.initialize_database(db)
    database.initialize_outreach_table(db)
    return db


class ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        if self.target:
            self.target(*self.args, **self.kwargs)


class TestFindAndFireRoutes(unittest.TestCase):
    def setUp(self):
        self.db = _make_test_db()
        web_app.app.config["TESTING"] = True
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = self.db
        self.client = web_app.app.test_client()
        web_app._find_fire_jobs.clear()

    def tearDown(self):
        web_app._find_fire_jobs.clear()
        database.DB_PATH = self._orig_db_path
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_find_and_fire_start_returns_job_id(self):
        fake_result = {
            "prospect_id": 1,
            "company": "Acme Dental",
            "website": "https://acme.test",
            "prospect_email": "owner@acme.test",
            "research": {},
            "email": {"subject": "Hi", "body": "Hello", "quality_score": 82},
            "pdf": {"url": "/proposals/acme.pdf", "filename": "acme.pdf"},
            "outreach_id": 101,
            "stage_statuses": {"research": "done", "email": "done", "pdf": "done"},
            "stage_errors": {},
            "status": "completed",
        }

        with mock.patch("threading.Thread", ImmediateThread), \
             mock.patch("google_maps_finder.find_and_add_prospects", return_value=[
                 {"id": 1, "company": "Acme Dental", "website": "https://acme.test", "email": ""}
             ]), \
             mock.patch("web_app._run_pipeline_for_db_prospect", return_value=fake_result):
            resp = self.client.post("/api/find-and-fire", json={
                "query": "dentists",
                "location": "Manchester",
                "limit": 1,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("job_id", data)
        self.assertIn("stage", data)
        self.assertIn("current_company", data)
        self.assertIn("current_index", data)
        self.assertIn("items", data)
        self.assertIn("message", data)

    def test_find_and_fire_status_returns_additive_fields(self):
        web_app._find_fire_jobs["job-123"] = {
            "status": "running",
            "stage": "email",
            "progress": 1,
            "total": 3,
            "results": [{"company": "Acme", "status": "completed"}],
            "items": [{"company": "Acme", "current_stage": "email"}],
            "error": None,
            "message": "Emailing Acme (1/3)",
            "current_company": "Acme",
            "current_index": 1,
        }

        resp = self.client.get("/api/find-and-fire/job-123")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["stage"], "email")
        self.assertEqual(data["current_company"], "Acme")
        self.assertEqual(data["current_index"], 1)
        self.assertEqual(data["message"], "Emailing Acme (1/3)")
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(len(data["items"]), 1)

    def test_find_and_fire_unknown_job_returns_404(self):
        resp = self.client.get("/api/find-and-fire/not-real")
        self.assertEqual(resp.status_code, 404)


class TestFindAndFireWorker(unittest.TestCase):
    def setUp(self):
        web_app._find_fire_jobs.clear()

    def tearDown(self):
        web_app._find_fire_jobs.clear()

    def test_discovery_failure_marks_job_as_error(self):
        job_id = "job-discovery-error"
        web_app._find_fire_jobs[job_id] = web_app._new_find_fire_job(3)

        def failing_finder(query, location, limit):
            raise RuntimeError("maps unavailable")

        web_app._run_find_fire_job(job_id, "dentists", "Manchester", 3, failing_finder)

        job = web_app._find_fire_jobs[job_id]
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["stage"], "error")
        self.assertEqual(job["progress"], 0)
        self.assertEqual(job["error"], "maps unavailable")

    def test_worker_keeps_running_after_partial_failure_and_appends_results_incrementally(self):
        job_id = "job-partial"
        web_app._find_fire_jobs[job_id] = web_app._new_find_fire_job(2)

        prospects = [
            {"id": 1, "company": "Alpha Co", "website": "https://alpha.test", "email": ""},
            {"id": 2, "company": "Beta Co", "website": "https://beta.test", "email": ""},
        ]
        snapshots = []

        def fake_pipeline(prospect, stage_hook=None):
            company = prospect["company"]
            stage_hook("research", "active", {"company": company})
            stage_hook("research", "done", {"company": company})
            stage_hook("email", "active", {"company": company})

            if company == "Alpha Co":
                stage_hook("email", "done", {"company": company})
                stage_hook("pdf", "active", {"company": company})
                stage_hook("pdf", "done", {"company": company})
                return {
                    "prospect_id": prospect["id"],
                    "company": company,
                    "website": prospect["website"],
                    "prospect_email": "alpha@alpha.test",
                    "research": {"niche": "Dental"},
                    "email": {"subject": "Alpha", "body": "Alpha body", "quality_score": 88},
                    "pdf": {"url": "/proposals/alpha.pdf", "filename": "alpha.pdf"},
                    "outreach_id": 201,
                    "stage_statuses": {"research": "done", "email": "done", "pdf": "done"},
                    "stage_errors": {},
                    "status": "completed",
                }

            snapshots.append(len(web_app._find_fire_jobs[job_id]["results"]))
            stage_hook("email", "error", {"company": company, "error": "smtp timeout"})
            stage_hook("pdf", "active", {"company": company})
            stage_hook("pdf", "error", {"company": company, "error": "pdf failed"})
            return {
                "prospect_id": prospect["id"],
                "company": company,
                "website": prospect["website"],
                "prospect_email": "",
                "research": {"niche": "Dental"},
                "email": {"subject": "", "body": "", "quality_score": 0},
                "pdf": {"url": "", "filename": "", "error": "pdf failed"},
                "outreach_id": None,
                "stage_statuses": {"research": "done", "email": "error", "pdf": "error"},
                "stage_errors": {"email": "smtp timeout", "pdf": "pdf failed"},
                "status": "partial_error",
                "error": "smtp timeout; pdf failed",
            }

        with mock.patch("web_app._run_pipeline_for_db_prospect", side_effect=fake_pipeline):
            web_app._run_find_fire_job(
                job_id,
                "dentists",
                "Manchester",
                2,
                lambda query, location, limit: prospects,
            )

        job = web_app._find_fire_jobs[job_id]
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["stage"], "done")
        self.assertEqual(job["progress"], 2)
        self.assertEqual(len(job["results"]), 2)
        self.assertEqual(snapshots, [1])
        self.assertEqual(job["results"][0]["status"], "completed")
        self.assertEqual(job["results"][1]["status"], "partial_error")
        self.assertEqual(job["items"][0]["status"], "completed")
        self.assertEqual(job["items"][1]["status"], "partial_error")
        self.assertEqual(job["items"][1]["stage_statuses"]["email"], "error")
        self.assertEqual(job["items"][1]["stage_statuses"]["pdf"], "error")


if __name__ == "__main__":
    unittest.main()
