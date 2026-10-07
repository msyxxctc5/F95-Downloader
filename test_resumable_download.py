import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from downloader import DownloadJob
import server


class TestResumableDownload(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.dl_dir = Path(self.temp_dir) / "downloads"
        self.dl_dir.mkdir(parents=True, exist_ok=True)
        self.lib_dir = Path(self.temp_dir) / "library"
        self.lib_dir.mkdir(parents=True, exist_ok=True)
        server.active_jobs.clear()
        server.queue_manager._queue.clear()
        server.queue_manager._running.clear()
        server.queue_manager.set_max_concurrent(3)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("downloader.load_config", return_value={"auto_extract": False})
    @patch("downloader.get_download_dir")
    @patch("downloader.get_library_root")
    @patch("downloader.rate_limited_unmask")
    @patch("downloader.resolve_direct_download_url")
    @patch("downloader.extract_archive")
    def test_01_range_resume_206(self, mock_extract, mock_resolve, mock_unmask, mock_lib, mock_dl, mock_cfg):
        """When .part file exists, requests.get should send Range header and append with 206."""
        mock_dl.return_value = self.dl_dir
        mock_lib.return_value = self.lib_dir
        mock_unmask.return_value = ("https://pixeldrain.com/u/abc123", None)
        mock_resolve.return_value = ("https://pixeldrain.com/api/file/abc123", "test_file.zip")
        mock_extract.return_value = (True, "OK")

        part_file = self.dl_dir / "test_file.zip.part"
        # Pre-populate 50 bytes
        part_file.write_bytes(b"A" * 50)

        # Mock response for remaining 50 bytes (total 100 bytes)
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        mock_resp.status_code = 206
        mock_resp.headers = {
            "Content-Range": "bytes 50-99/100",
            "Content-Type": "application/octet-stream"
        }
        mock_resp.iter_content.return_value = [b"B" * 50]
        mock_resp.raise_for_status = MagicMock()

        with patch("downloader.requests.get", return_value=mock_resp) as mock_get:
            job = DownloadJob("ArtistA", "2026-01", "https://f95zone.to/masked/test")
            job.run()

            # Verify Range header was sent
            args, kwargs = mock_get.call_args
            self.assertIn("Range", kwargs.get("headers", {}))
            self.assertEqual(kwargs["headers"]["Range"], "bytes=50-")

            # Verify job completed and file combined (50 + 50 = 100 bytes)
            self.assertEqual(job.status, "COMPLETED")
            final_file = self.dl_dir / "test_file.zip"
            self.assertTrue(final_file.exists())
            self.assertEqual(final_file.stat().st_size, 100)
            self.assertEqual(final_file.read_bytes(), b"A" * 50 + b"B" * 50)

    @patch("downloader.load_config", return_value={"auto_extract": False})
    @patch("downloader.get_download_dir")
    @patch("downloader.get_library_root")
    @patch("downloader.rate_limited_unmask")
    @patch("downloader.resolve_direct_download_url")
    @patch("downloader.extract_archive")
    def test_02_server_ignores_range_200_fallback(self, mock_extract, mock_resolve, mock_unmask, mock_lib, mock_dl, mock_cfg):
        """When server ignores Range and responds 200, it should safely overwrite from byte 0."""
        mock_dl.return_value = self.dl_dir
        mock_lib.return_value = self.lib_dir
        mock_unmask.return_value = ("https://pixeldrain.com/u/abc123", None)
        mock_resolve.return_value = ("https://pixeldrain.com/api/file/abc123", "test_file.zip")
        mock_extract.return_value = (True, "OK")

        part_file = self.dl_dir / "test_file.zip.part"
        part_file.write_bytes(b"STALE_OLD_CONTENT_THAT_SHOULD_BE_CLEARED")

        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        mock_resp.status_code = 200
        mock_resp.headers = {
            "Content-Length": "60",
            "Content-Type": "application/octet-stream"
        }
        mock_resp.iter_content.return_value = [b"C" * 60]
        mock_resp.raise_for_status = MagicMock()

        with patch("downloader.requests.get", return_value=mock_resp):
            job = DownloadJob("ArtistA", "2026-01", "https://f95zone.to/masked/test")
            job.run()

            self.assertEqual(job.status, "COMPLETED")
            final_file = self.dl_dir / "test_file.zip"
            self.assertTrue(final_file.exists())
            self.assertEqual(final_file.stat().st_size, 60)
            self.assertEqual(final_file.read_bytes(), b"C" * 60)

    @patch("downloader.get_download_dir")
    @patch("downloader.get_library_root")
    @patch("downloader.rate_limited_unmask")
    @patch("downloader.resolve_direct_download_url")
    def test_03_pause_and_cancel_lifecycle(self, mock_resolve, mock_unmask, mock_lib, mock_dl):
        """Test pause keeps .part file while cancel deletes .part file."""
        mock_dl.return_value = self.dl_dir
        mock_lib.return_value = self.lib_dir
        mock_unmask.return_value = ("https://pixeldrain.com/u/abc123", None)
        mock_resolve.return_value = ("https://pixeldrain.com/api/file/abc123", "test_file.zip")

        part_file = self.dl_dir / "test_file.zip.part"

        # 1. Pause test
        job = DownloadJob("ArtistA", "2026-01", "https://f95zone.to/masked/test")

        def pause_during_stream(*args, **kwargs):
            job.pause()
            return [b"chunk1", b"chunk2"]

        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": "1000", "Content-Type": "application/octet-stream"}
        mock_resp.iter_content.side_effect = pause_during_stream
        mock_resp.raise_for_status = MagicMock()

        with patch("downloader.requests.get", return_value=mock_resp):
            job.run()
            self.assertEqual(job.status, "PAUSED")
            # .part file must NOT be deleted on pause!
            self.assertTrue(part_file.exists())

        # 2. Cancel test
        job2 = DownloadJob("ArtistA", "2026-01", "https://f95zone.to/masked/test")

        def cancel_during_stream(*args, **kwargs):
            job2.cancel()
            return [b"chunk1"]

        mock_resp2 = MagicMock()
        mock_resp2.__enter__.return_value = mock_resp2
        mock_resp2.__exit__.return_value = None
        mock_resp2.status_code = 200
        mock_resp2.headers = {"Content-Length": "1000", "Content-Type": "application/octet-stream"}
        mock_resp2.iter_content.side_effect = cancel_during_stream
        mock_resp2.raise_for_status = MagicMock()

        with patch("downloader.requests.get", return_value=mock_resp2):
            job2.run()
            self.assertEqual(job2.status, "CANCELLED")
            # .part file must be removed on cancel
            self.assertFalse(part_file.exists())
            # .part file must be removed on cancel
            self.assertFalse(part_file.exists())

    def test_04_api_pause_resume_cancel(self):
        """Test API endpoints for pause, resume and cancel."""
        client = TestClient(server.app)

        dummy_job = DownloadJob("TestAuthor", "2026-02", "https://f95zone.to/masked/demo")
        dummy_job.status = "DOWNLOADING"
        server.active_jobs["TestAuthor_2026-02"] = dummy_job

        # 1. Pause
        res = client.post("/api/download/pause", json={"job_id": "TestAuthor_2026-02"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(dummy_job.status, "PAUSED")

        # 2. Resume
        with patch.object(dummy_job, "run"):
            res = client.post("/api/download/resume", json={"job_id": "TestAuthor_2026-02"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(dummy_job.status, "PENDING")

        # 3. Cancel
        res = client.post("/api/download/cancel", json={"job_id": "TestAuthor_2026-02"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(dummy_job.status, "CANCELLED")


if __name__ == "__main__":
    unittest.main()
