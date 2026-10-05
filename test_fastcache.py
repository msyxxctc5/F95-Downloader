import os
import time
import shutil
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

import scanner
import fastcache
from server import app

def test_fastcache_mechanics():
    print("Testing fastcache core mechanics...")
    temp_root = Path(tempfile.mkdtemp(prefix="test_lib_fast_"))
    try:
        # Create 2 authors
        a1 = temp_root / "ArtistOne"
        a1.mkdir()
        (a1 / "2024-01").mkdir()
        (a1 / "2024-01" / "video1.mp4").write_text("dummy")

        a2 = temp_root / "ArtistTwo"
        a2.mkdir()
        (a2 / "2024-02").mkdir()
        (a2 / "2024-02" / "video2.mp4").write_text("dummy")

        # 1. Initial list_cached (scans new authors)
        t0 = time.time()
        authors, online = fastcache.list_cached(str(temp_root))
        t1 = time.time()
        assert online is True
        assert len(authors) == 2
        names = {a["name"] for a in authors}
        assert names == {"ArtistOne", "ArtistTwo"}
        print(f"[OK] Initial scan populated cache in {t1 - t0:.4f}s")

        # 2. Second list_cached (cold hit: instant from cache, 0 subfolder stat)
        t0 = time.time()
        authors2, online2 = fastcache.list_cached(str(temp_root))
        t1 = time.time()
        assert online2 is True
        assert len(authors2) == 2
        print(f"[OK] Cache-first list_cached completed in {t1 - t0:.4f}s")

        # 3. Add a new author (ArtistThree)
        a3 = temp_root / "ArtistThree"
        a3.mkdir()
        (a3 / "2024-03").mkdir()
        (a3 / "2024-03" / "video3.mp4").write_text("dummy")

        authors3, _ = fastcache.list_cached(str(temp_root))
        assert len(authors3) == 3
        assert any(a["name"] == "ArtistThree" for a in authors3)
        print("[OK] New author was automatically detected and cached")

        # 4. Delete an author (ArtistTwo)
        shutil.rmtree(a2)
        authors4, _ = fastcache.list_cached(str(temp_root))
        assert len(authors4) == 2
        assert not any(a["name"] == "ArtistTwo" for a in authors4)
        print("[OK] Deleted author was evicted from cache")

        # 5. Offline resilience (drive disconnected / fake path)
        fake_path = temp_root / "non_existent_drive"
        offline_authors, online_flag = fastcache.list_cached(str(fake_path))
        assert online_flag is False
        assert offline_authors == []

        # Check existing cache was NOT destroyed
        authors_still_there, is_online = fastcache.list_cached(str(temp_root))
        assert is_online is True
        assert len(authors_still_there) == 2
        print("[OK] Offline library test passed without destroying cache")

        # 6. Background revalidation
        # Modify ArtistOne
        (a1 / "2024-05").mkdir()
        (a1 / "2024-05" / "new.mp4").write_text("new")

        fastcache.revalidate_all(str(temp_root), throttle=0.01)
        assert "ArtistOne" in fastcache.STATE["updated"]
        assert fastcache.STATE["running"] is False
        print("[OK] Throttled revalidate_all detected and updated modified author")

    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

def test_api_endpoints():
    print("Testing API integration with fastcache...")
    client = TestClient(app)
    
    # 1. /api/library/status
    res = client.get("/api/library/status")
    assert res.status_code == 200
    st = res.json()
    assert "online" in st
    assert "running" in st
    assert "checked" in st
    assert "total" in st
    print("[OK] /api/library/status returned expected schema")

    # 2. /api/authors
    res = client.get("/api/authors")
    assert res.status_code == 200
    authors = res.json()
    assert isinstance(authors, list)
    print(f"[OK] /api/authors responded with {len(authors)} authors")

if __name__ == "__main__":
    test_fastcache_mechanics()
    test_api_endpoints()
    print("\nALL FASTCACHE TESTS PASSED SUCCESSFULLY! [DONE]")
