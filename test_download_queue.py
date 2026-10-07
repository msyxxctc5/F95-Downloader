import time
import threading
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from fastapi.testclient import TestClient

from downloader import DownloadJob, DownloadQueueManager
import config
import server


class TestDownloadQueue(unittest.TestCase):
    def setUp(self):
        self.mock_jobs_dict = {}
        server.active_jobs.clear()
        server.queue_manager._queue.clear()
        server.queue_manager._running.clear()

    def tearDown(self):
        server.active_jobs.clear()
        server.queue_manager._queue.clear()
        server.queue_manager._running.clear()
        server.queue_manager.set_max_concurrent(3)

    def test_01_fifo_queue_with_concurrency_limit_1(self):
        """When max_concurrent is 1, extra jobs must be QUEUED and start sequentially upon completion."""
        manager = DownloadQueueManager(max_concurrent=1, jobs_dict=self.mock_jobs_dict)

        job1_done = threading.Event()
        job2_done = threading.Event()
        job3_done = threading.Event()

        job1 = DownloadJob("AuthorA", "2026-01", "https://f95zone.to/masked/1")
        job2 = DownloadJob("AuthorA", "2026-02", "https://f95zone.to/masked/2")
        job3 = DownloadJob("AuthorA", "2026-03", "https://f95zone.to/masked/3")

        def run_job1(*args, **kwargs):
            job1.status = "DOWNLOADING"
            job1_done.wait(timeout=5)
            job1.status = "COMPLETED"

        def run_job2(*args, **kwargs):
            job2.status = "DOWNLOADING"
            job2_done.wait(timeout=5)
            job2.status = "COMPLETED"

        def run_job3(*args, **kwargs):
            job3.status = "DOWNLOADING"
            job3_done.wait(timeout=5)
            job3.status = "COMPLETED"

        with patch.object(job1, "run", side_effect=run_job1), \
             patch.object(job2, "run", side_effect=run_job2), \
             patch.object(job3, "run", side_effect=run_job3):

            # Submit Job 1 -> should start immediately
            s1 = manager.submit("j1", job1)
            self.assertEqual(s1, "started")
            self.assertEqual(job1.status, "DOWNLOADING")
            self.assertIsNone(manager.get_queue_position("j1"))

            # Submit Job 2 -> should be queued at position 1
            s2 = manager.submit("j2", job2)
            self.assertEqual(s2, "queued")
            self.assertEqual(job2.status, "QUEUED")
            self.assertEqual(manager.get_queue_position("j2"), 1)

            # Submit Job 3 -> should be queued at position 2
            s3 = manager.submit("j3", job3)
            self.assertEqual(s3, "queued")
            self.assertEqual(job3.status, "QUEUED")
            self.assertEqual(manager.get_queue_position("j3"), 2)

            stats = manager.get_stats()
            self.assertEqual(stats["running_count"], 1)
            self.assertEqual(stats["queued_count"], 2)

            # Finish Job 1 -> Job 2 should automatically start
            job1_done.set()
            for _ in range(50):
                if job2.status == "DOWNLOADING":
                    break
                time.sleep(0.02)

            self.assertEqual(job2.status, "DOWNLOADING")
            self.assertIsNone(manager.get_queue_position("j2"))
            self.assertEqual(manager.get_queue_position("j3"), 1)

            # Finish Job 2 -> Job 3 should automatically start
            job2_done.set()
            for _ in range(50):
                if job3.status == "DOWNLOADING":
                    break
                time.sleep(0.02)

            self.assertEqual(job3.status, "DOWNLOADING")
            self.assertIsNone(manager.get_queue_position("j3"))

            # Finish Job 3
            job3_done.set()
            for _ in range(50):
                if manager.get_stats()["running_count"] == 0:
                    break
                time.sleep(0.02)

            final_stats = manager.get_stats()
            self.assertEqual(final_stats["running_count"], 0)
            self.assertEqual(final_stats["queued_count"], 0)

    def test_02_pause_active_job_promotes_queued_job(self):
        """Pausing an active job frees up the slot and promotes the next queued job."""
        manager = DownloadQueueManager(max_concurrent=1, jobs_dict=self.mock_jobs_dict)

        job1_started = threading.Event()
        job1_exit = threading.Event()
        job2_done = threading.Event()

        job1 = DownloadJob("AuthorB", "2026-01", "https://f95zone.to/masked/b1")
        job2 = DownloadJob("AuthorB", "2026-02", "https://f95zone.to/masked/b2")

        def run_job1(*args, **kwargs):
            job1.status = "DOWNLOADING"
            job1_started.set()
            while not job1._pause_event.is_set() and not job1_exit.is_set():
                time.sleep(0.02)
            return

        def run_job2(*args, **kwargs):
            job2.status = "DOWNLOADING"
            job2_done.wait(timeout=5)
            job2.status = "COMPLETED"

        with patch.object(job1, "run", side_effect=run_job1), \
             patch.object(job2, "run", side_effect=run_job2):

            manager.submit("b1", job1)
            job1_started.wait(timeout=3)
            self.assertEqual(job1.status, "DOWNLOADING")

            manager.submit("b2", job2)
            self.assertEqual(job2.status, "QUEUED")

            # Pause job1
            manager.pause("b1")
            self.assertEqual(job1.status, "PAUSED")

            # Wait for job2 to be promoted and set to DOWNLOADING
            for _ in range(50):
                if job2.status == "DOWNLOADING":
                    break
                time.sleep(0.02)

            self.assertEqual(job2.status, "DOWNLOADING")
            self.assertEqual(manager.get_stats()["queued_count"], 0)

            # Now resume job1 -> since job2 is actively running, job1 enters queue
            res = manager.resume("b1")
            self.assertEqual(res, "queued")
            self.assertEqual(job1.status, "QUEUED")
            self.assertEqual(manager.get_queue_position("b1"), 1)

            job2_done.set()

    def test_03_cancel_queued_job(self):
        """Cancelling a queued job removes it from queue without launching it."""
        manager = DownloadQueueManager(max_concurrent=1, jobs_dict=self.mock_jobs_dict)

        job1_done = threading.Event()
        job1 = DownloadJob("AuthorC", "2026-01", "https://f95zone.to/masked/c1")
        job2 = DownloadJob("AuthorC", "2026-02", "https://f95zone.to/masked/c2")
        job3 = DownloadJob("AuthorC", "2026-03", "https://f95zone.to/masked/c3")

        def run_job1(*args, **kwargs):
            job1.status = "DOWNLOADING"
            job1_done.wait(timeout=5)
            job1.status = "COMPLETED"

        def run_job2(*args, **kwargs):
            job2.status = "DOWNLOADING"

        def run_job3(*args, **kwargs):
            job3.status = "DOWNLOADING"

        with patch.object(job1, "run", side_effect=run_job1), \
             patch.object(job2, "run", side_effect=run_job2), \
             patch.object(job3, "run", side_effect=run_job3):

            manager.submit("c1", job1)
            manager.submit("c2", job2)
            manager.submit("c3", job3)

            self.assertEqual(manager.get_queue_position("c2"), 1)
            self.assertEqual(manager.get_queue_position("c3"), 2)

            # Cancel c2
            manager.cancel("c2")
            self.assertEqual(job2.status, "CANCELLED")
            self.assertIsNone(manager.get_queue_position("c2"))
            self.assertEqual(manager.get_queue_position("c3"), 1)

            # Release job 1 -> job 3 must start, skipping cancelled job 2
            job1_done.set()
            for _ in range(50):
                if job3.status == "DOWNLOADING":
                    break
                time.sleep(0.02)

            self.assertEqual(job3.status, "DOWNLOADING")

    def test_04_dynamic_concurrency_limit_increase(self):
        """Increasing concurrency limit immediately promotes waiting queued jobs."""
        manager = DownloadQueueManager(max_concurrent=1, jobs_dict=self.mock_jobs_dict)

        job1 = DownloadJob("AuthorD", "2026-01", "https://f95zone.to/masked/d1")
        job2 = DownloadJob("AuthorD", "2026-02", "https://f95zone.to/masked/d2")
        job3 = DownloadJob("AuthorD", "2026-03", "https://f95zone.to/masked/d3")

        stop_all = threading.Event()

        def block_run(j):
            def _runner(*args, **kwargs):
                j.status = "DOWNLOADING"
                stop_all.wait(timeout=5)
                j.status = "COMPLETED"
            return _runner

        with patch.object(job1, "run", side_effect=block_run(job1)), \
             patch.object(job2, "run", side_effect=block_run(job2)), \
             patch.object(job3, "run", side_effect=block_run(job3)):

            manager.submit("d1", job1)
            manager.submit("d2", job2)
            manager.submit("d3", job3)

            self.assertEqual(manager.get_stats()["running_count"], 1)
            self.assertEqual(manager.get_stats()["queued_count"], 2)

            # Dynamically increase max_concurrent from 1 to 3
            manager.set_max_concurrent(3)

            # All queued jobs should be immediately promoted
            for _ in range(50):
                if manager.get_stats()["running_count"] == 3:
                    break
                time.sleep(0.02)

            stats = manager.get_stats()
            self.assertEqual(stats["running_count"], 3)
            self.assertEqual(stats["queued_count"], 0)
            self.assertEqual(stats["max_concurrent"], 3)
            self.assertEqual(job1.status, "DOWNLOADING")
            self.assertEqual(job2.status, "DOWNLOADING")
            self.assertEqual(job3.status, "DOWNLOADING")

            stop_all.set()

    def test_05_api_config_and_queue_integration(self):
        """Test FastAPI endpoints for max_concurrent_downloads and queue status."""
        client = TestClient(server.app)

        # 1. Update config to max_concurrent_downloads = 2
        res = client.post("/api/config", json={"max_concurrent_downloads": 2})
        self.assertEqual(res.status_code, 200)
        cfg_data = res.json()["config"]
        self.assertEqual(cfg_data["max_concurrent_downloads"], 2)

        # 2. Check queue stats endpoint
        stats_res = client.get("/api/jobs/queue_stats")
        self.assertEqual(stats_res.status_code, 200)
        self.assertEqual(stats_res.json()["max_concurrent"], 2)

        # 3. Clean active jobs and test submission queue
        server.queue_manager.clear_finished()
        server.queue_manager.set_max_concurrent(1)

        block_run = threading.Event()

        def mock_job_run(job_inst, *args, **kwargs):
            job_inst.status = "DOWNLOADING"
            block_run.wait(timeout=5)
            job_inst.status = "COMPLETED"

        with patch.object(DownloadJob, "run", autospec=True, side_effect=mock_job_run):
            # Submit task 1
            r1 = client.post("/api/download/start", json={
                "author": "ApiTest",
                "month": "2026-01",
                "masked_url": "https://f95zone.to/masked/api1"
            })
            self.assertEqual(r1.json()["status"], "started")

            # Submit task 2 (should be queued because limit is 1)
            r2 = client.post("/api/download/start", json={
                "author": "ApiTest",
                "month": "2026-02",
                "masked_url": "https://f95zone.to/masked/api2"
            })
            self.assertEqual(r2.json()["status"], "queued")

            # Check /api/jobs
            jobs_res = client.get("/api/jobs")
            jobs = jobs_res.json()
            self.assertIn("ApiTest_2026-01", jobs)
            self.assertIn("ApiTest_2026-02", jobs)
            self.assertEqual(jobs["ApiTest_2026-02"]["status"], "QUEUED")
            self.assertEqual(jobs["ApiTest_2026-02"]["queue_position"], 1)

            block_run.set()


if __name__ == "__main__":
    unittest.main()
