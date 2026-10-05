import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import requests

from config import (
    load_config, get_library_root, get_download_dir,
    get_user_agent, get_7z_custom_path, DEFAULT_CONFIG
)
from extractor import get_7z_path
import idm_helper
from diff_engine import unmask_f95_link_detailed, unmask_f95_link
from downloader import rate_limited_unmask
import server
from fastapi.testclient import TestClient

class TestP2EngineeringFixes(unittest.TestCase):

    def test_01_config_centralization_and_privacy(self):
        """Verify DEFAULT_CONFIG contains no hardcoded personal drives or usernames."""
        self.assertNotIn("H:\\akinaclub", DEFAULT_CONFIG["library_root"])
        self.assertNotIn("Despa", DEFAULT_CONFIG["download_dir"])
        self.assertIn("user_agent", DEFAULT_CONFIG)
        self.assertIn("seven_zip_path", DEFAULT_CONFIG)

        lib_root = get_library_root()
        self.assertIsInstance(lib_root, Path)

        dl_dir = get_download_dir()
        self.assertIsInstance(dl_dir, Path)
        self.assertNotIn("Despa", str(dl_dir).lower() if "despa" not in os.environ.get("USERNAME", "").lower() else "")

        ua = get_user_agent()
        self.assertIn("Mozilla", ua)

    def test_02_7z_detection_and_no_aomei(self):
        """Verify 7z detection no longer searches AOMEI backupper path."""
        import extractor
        # Inspect source code of extractor to ensure AOMEI string does not exist
        extractor_code = Path(extractor.__file__).read_text(encoding="utf-8")
        self.assertNotIn("AOMEI", extractor_code)

        # Test custom 7z path injection
        with patch("config.load_config", return_value={"seven_zip_path": sys.executable}):
            self.assertEqual(get_7z_path(), sys.executable)

    def test_03_idm_helper_directory_consistency(self):
        """Verify IDM default output directory equals configured download_dir."""
        with patch("idm_helper.find_idm_path", return_value="dummy_idm.exe"), \
             patch("subprocess.Popen") as mock_popen:
            idm_helper.download_with_idm("https://example.com/file.zip")
            self.assertTrue(mock_popen.called)
            cmd = mock_popen.call_args[0][0]
            # cmd is: [idm_exe, '/d', url, '/p', output_dir, '/n']
            p_idx = cmd.index("/p")
            output_dir_arg = cmd[p_idx + 1]
            self.assertEqual(output_dir_arg, str(get_download_dir()))

    def test_04_unmask_detailed_diagnostics(self):
        """Verify unmask_f95_link_detailed correctly distinguishes failure reasons."""
        masked = "https://f95zone.to/masked/abc123xyz"

        # 1. No xf_user cookie
        url, err = unmask_f95_link_detailed(masked, {})
        self.assertIsNone(url)
        self.assertIn("未配置 F95zone Cookie", err)

        # 2. 403 Forbidden (Cookie expired or Cloudflare turnstile)
        mock_resp_403 = MagicMock()
        mock_resp_403.status_code = 403
        with patch("requests.post", return_value=mock_resp_403):
            url, err = unmask_f95_link_detailed(masked, {"xf_user": "dummy_cookie"})
            self.assertIsNone(url)
            self.assertIn("403", err)
            self.assertIn("Cloudflare", err)

        # 3. 429 Rate Limit
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        with patch("requests.post", return_value=mock_resp_429):
            url, err = unmask_f95_link_detailed(masked, {"xf_user": "dummy_cookie"})
            self.assertIsNone(url)
            self.assertIn("429", err)

        # 4. Timeout
        with patch("requests.post", side_effect=requests.exceptions.Timeout("Read timeout")):
            url, err = unmask_f95_link_detailed(masked, {"xf_user": "dummy_cookie"})
            self.assertIsNone(url)
            self.assertIn("超时", err)

        # 5. Success 200
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.json.return_value = {"status": "ok", "msg": "https://pixeldrain.com/u/valid123"}
        with patch("requests.post", return_value=mock_resp_200):
            url, err = unmask_f95_link_detailed(masked, {"xf_user": "dummy_cookie"})
            self.assertEqual(url, "https://pixeldrain.com/u/valid123")
            self.assertIsNone(err)

            # Test backwards-compatible unmask_f95_link wrapper
            compat_url = unmask_f95_link(masked, {"xf_user": "dummy_cookie"})
            self.assertEqual(compat_url, "https://pixeldrain.com/u/valid123")

    def test_05_rate_limited_unmask_throttling(self):
        """Verify rate_limited_unmask introduces minimum interval to prevent rate limit."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "msg": "https://pixeldrain.com/u/1"}

        with patch("requests.post", return_value=mock_resp):
            t0 = time.time()
            rate_limited_unmask("https://f95zone.to/masked/test1", {"xf_user": "c1"})
            rate_limited_unmask("https://f95zone.to/masked/test2", {"xf_user": "c1"})
            duration = time.time() - t0
            self.assertGreaterEqual(duration, 1.0, f"Rate limiting cooldown violated: duration was {duration:.2f}s")

    def test_06_ingest_no_syntax_warnings(self):
        """Verify ingest.py docstrings do not trigger SyntaxWarning on Python 3.12."""
        import warnings
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            import ingest
            # Ensure no SyntaxWarning was raised during import
            syntax_warnings = [w for w in recorded if issubclass(w.category, SyntaxWarning)]
            self.assertEqual(len(syntax_warnings), 0, f"Found SyntaxWarning: {syntax_warnings}")

    def test_07_server_api_p2_endpoints(self):
        """Verify server config and unmask error reporting endpoints."""
        client = TestClient(server.app)

        # 1. Config endpoint exposes user_agent and download_dir
        res = client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("user_agent", data)
        self.assertIn("download_dir", data)
        self.assertIn("library_root", data)

        # 2. Unmask endpoint detail reporting on failure
        with patch("server.unmask_f95_link_detailed", return_value=(None, "论坛访问被拒绝 (403): Cookie 可能已过期")):
            res = client.get("/api/unmask?url=https://f95zone.to/masked/demo123")
            self.assertEqual(res.status_code, 400)
            self.assertIn("403", res.json().get("detail", ""))

        # 3. IDM download endpoint
        with patch("server.unmask_f95_link_detailed", return_value=("https://pixeldrain.com/u/demo123", None)), \
             patch("server.download_with_idm", return_value=True):
            res = client.post("/api/idm/download", json={
                "author": "DemoAuthor",
                "month": "2026-01",
                "masked_url": "https://f95zone.to/masked/demo123"
            })
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "ok")

if __name__ == "__main__":
    unittest.main()
