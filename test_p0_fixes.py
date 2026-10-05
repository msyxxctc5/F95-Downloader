import os
import shutil
import tempfile
import threading
from pathlib import Path
from fastapi.testclient import TestClient

def test_scanner_cache():
    print("Testing scanner cache protections...")
    import scanner
    assert hasattr(scanner, "CACHE_VERSION"), "CACHE_VERSION missing"
    assert hasattr(scanner, "_cache_lock"), "_cache_lock missing"
    assert isinstance(scanner._cache_lock, type(threading.RLock())), "_cache_lock should be RLock"

    # Test cache contamination protection
    test_dir = Path(tempfile.mkdtemp(prefix="test_lib_"))
    try:
        author_dir = test_dir / "ArtistA"
        author_dir.mkdir()
        (author_dir / "2024-01").mkdir()
        (author_dir / "2024-01" / "file.mp4").write_text("dummy")

        # Scan
        res1 = scanner.scan_author_directory_cached(author_dir, force=True)
        assert res1["name"] == "ArtistA"
        
        # Mutate returned object
        res1["thread_url"] = "https://polluted.url"
        res1["missing_count"] = 999

        # Scan again (from cache)
        res2 = scanner.scan_author_directory_cached(author_dir, force=False)
        assert "thread_url" not in res2, "Cache was contaminated by caller mutation!"
        assert "missing_count" not in res2, "Cache was contaminated by caller mutation!"

        # Test CACHE_VERSION invalidation
        cache = scanner.load_library_cache()
        assert "ArtistA" in cache
        assert cache["ArtistA"].get("v") == scanner.CACHE_VERSION
        
        # Simulate outdated version
        cache["ArtistA"]["v"] = scanner.CACHE_VERSION - 1
        cache["ArtistA"]["data"]["stale_marker"] = True
        
        # Next scan should ignore stale version and re-scan
        res3 = scanner.scan_author_directory_cached(author_dir, force=False)
        assert "stale_marker" not in res3, "Outdated cache version was not invalidated!"
        print("[OK] Scanner cache tests passed!")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

def test_server_security():
    print("Testing server security (cookies, SSRF, host/origin)...")
    from server import app, is_valid_f95_thread_url
    client = TestClient(app)

    # 1. URL validator
    assert is_valid_f95_thread_url("https://f95zone.to/threads/test-thread.12345/")
    assert is_valid_f95_thread_url("https://www.f95zone.to/threads/abc.999/")
    assert not is_valid_f95_thread_url("http://f95zone.to/threads/abc.123/") # no http
    assert not is_valid_f95_thread_url("https://evil.com/threads/abc.123/") # wrong domain
    assert not is_valid_f95_thread_url("https://f95zone.to/members/admin.1/") # not a thread
    assert not is_valid_f95_thread_url("file:///etc/passwd")

    # 2. Config cookie leakage
    res = client.get("/api/config")
    assert res.status_code == 200
    cfg = res.json()
    assert "xf_user" not in cfg, "Plaintext xf_user leaked in GET /api/config!"
    assert "xf_user_masked" in cfg or not cfg.get("has_xf_user")

    # 3. SSRF in bind_author_thread
    res = client.post("/api/authors/bind", json={"author": "Test", "thread_url": "http://169.254.169.254/latest/meta-data"})
    assert res.status_code == 400, "SSRF URL was not blocked!"

    # 4. Host header check
    res = client.get("/api/config", headers={"host": "evil.com"})
    assert res.status_code == 403, "Invalid host header was not blocked!"

    # 5. Cross-Origin check
    res = client.get("/api/config", headers={"origin": "https://malicious-website.com"})
    assert res.status_code == 403, "Malicious cross-origin request was not blocked!"

    print("[OK] Server security tests passed!")

def test_extractor_merge():
    print("Testing recursive merge in extractor...")
    from extractor import _recursive_merge_dir
    src = Path(tempfile.mkdtemp(prefix="test_src_"))
    dst = Path(tempfile.mkdtemp(prefix="test_dst_"))
    try:
        # dst has existing subfolder with old file
        (dst / "subfolder").mkdir()
        (dst / "subfolder" / "existing_file.txt").write_text("keep me")

        # src has subfolder with new file and overwrite file
        (src / "subfolder").mkdir()
        (src / "subfolder" / "new_file.txt").write_text("new content")

        _recursive_merge_dir(src, dst)

        assert (dst / "subfolder" / "existing_file.txt").exists(), "Existing subfolder file was wiped out by merge!"
        assert (dst / "subfolder" / "new_file.txt").exists(), "New file was not merged!"
        print("[OK] Extractor recursive merge test passed!")
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)

def test_ingest_path_restriction():
    print("Testing ingest archive path restrictions...")
    from ingest import ingest_archive_to_library
    # Test path outside allowed roots
    res = ingest_archive_to_library(r"C:\Windows\System32\cmd.exe", "Author", "2024-01")
    assert res["status"] == "error", "Ingest did not reject unsafe path!"
    print("[OK] Ingest path restriction test passed!")

if __name__ == "__main__":
    test_scanner_cache()
    test_server_security()
    test_extractor_merge()
    test_ingest_path_restriction()
    print("\nALL P0 FIXES VERIFIED SUCCESSFULLY! [DONE]")
