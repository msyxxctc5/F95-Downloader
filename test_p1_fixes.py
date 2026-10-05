import re
from bs4 import BeautifulSoup
from scanner import normalize_month
from diff_engine import (
    is_download_link,
    extract_password_from_text,
    extract_universal_label,
    check_local_existence
)

def test_normalize_month():
    print("Testing normalize_month edge cases...")
    cases = [
        ("March 2021", "2021-03"),
        ("2021 March", "2021-03"),
        ("2021 Mar", "2021-03"),
        ("2022 Summary", ""),
        ("2023 Decided", ""),
        ("2024 Smart", ""),
        ("2021 Mayday", ""),
        ("May 2021", "2021-05"),
        ("2021-05", "2021-05"),
        ("2020.01", "2020-01"),
        ("03-2019", "2019-03"),
        ("202103", "2021-03"),
    ]
    for text, expected in cases:
        got = normalize_month(text)
        assert got == expected, f"Failed for '{text}': expected '{expected}', got '{got}'"
    print("[OK] normalize_month tests passed!")

def test_is_download_link():
    print("Testing is_download_link...")
    html = '''
    <a href="https://pixeldrain.com/u/abc123">Pixeldrain File</a>
    <a href="https://pixeldrain.com/l/folder123">Pixeldrain List</a>
    <a href="https://f95zone.to/masked/x9y8z7/">F95 Masked</a>
    <a href="https://mega.nz/file/xyz">Mega File</a>
    <a href="https://twitter.com/mega_fan">Twitter (False Host)</a>
    <a href="https://example.com/art?ref=pixeldrain">Referer Substring</a>
    <a href="https://f95zone.to/threads/sample.123/">F95 Thread Page</a>
    <a href="https://attachments.f95zone.to/123.jpg">F95 Attachment</a>
    '''
    soup = BeautifulSoup(html, 'html.parser')
    tags = soup.find_all('a')
    
    # Valid download links
    assert is_download_link(tags[0]) == True, "Pixeldrain file should be True"
    assert is_download_link(tags[1]) == True, "Pixeldrain list should be True"
    assert is_download_link(tags[2]) == True, "F95 masked link should be True"
    assert is_download_link(tags[3]) == True, "Mega link should be True"

    # Invalid / False positives
    assert is_download_link(tags[4]) == False, "Twitter link should be False"
    assert is_download_link(tags[5]) == False, "Referer parameter should be False"
    assert is_download_link(tags[6]) == False, "F95 thread page should be False"
    assert is_download_link(tags[7]) == False, "F95 attachment should be False"
    print("[OK] is_download_link tests passed!")

def test_extract_password():
    print("Testing extract_password_from_text...")
    assert extract_password_from_text("Password: secret_pass (case sensitive)") == "secret_pass"
    assert extract_password_from_text("Archive Password: \"f95zone\"") == "f95zone"
    assert extract_password_from_text("pass: f95zone.") == "f95zone"
    assert extract_password_from_text("Pass: none") == ""
    assert extract_password_from_text("Password: N/A") == ""
    assert extract_password_from_text("Password: -") == ""
    assert extract_password_from_text("You can bypass this firewall. The exam was passed.") == ""
    assert extract_password_from_text("The compass is pointing North.") == ""
    print("[OK] extract_password_from_text tests passed!")

def test_heuristic_blacklist():
    print("Testing extract_universal_label blacklist...")
    assert extract_universal_label("Bonus:") is None
    assert extract_universal_label("Extras:") is None
    assert extract_universal_label("Patreon:") is None
    assert extract_universal_label("Fanbox:") is None
    assert extract_universal_label("Download:") is None
    assert extract_universal_label("Kaiju No. 8:") == "Kaiju No. 8"
    assert extract_universal_label("Sono Bisque Doll:") == "Sono Bisque Doll"
    print("[OK] extract_universal_label blacklist tests passed!")

def test_check_local_existence():
    print("Testing check_local_existence...")
    local_data = {
        "months": ["2021-03", "2022-05"],
        "terms": ["Term 12", "Term 55"],
        "media_assets": [
            {"name": "[2021-03] Set.zip", "rel_path": "2021-03/Set.zip"},
            {"name": "Kaiju No. 8 Vol 1.zip", "rel_path": "Kaiju No. 8 Vol 1.zip"},
            {"name": "Smart Collection.zip", "rel_path": "Smart Collection.zip"},
        ]
    }
    # Month matches
    assert check_local_existence("2021-03", local_data)[0] == True
    assert check_local_existence("March 2021", local_data)[0] == True
    assert check_local_existence("2023-01", local_data)[0] == False
    
    # Term matches
    assert check_local_existence("Term 12", local_data)[0] == True
    assert check_local_existence("Term 99", local_data)[0] == False
    
    # Title / Number matches
    assert check_local_existence("Kaiju No. 8", local_data)[0] == True
    
    # False positives prevented
    assert check_local_existence("Bonus", local_data)[0] == False
    assert check_local_existence("Art", local_data)[0] == False
    assert check_local_existence("General", local_data)[0] == False
    assert check_local_existence("Unknown / General", local_data)[0] == False
    print("[OK] check_local_existence tests passed!")

def test_pixeldrain_resolution():
    print("Testing Pixeldrain /u/ and /l/ resolution...")
    import unittest.mock as mock
    from downloader import resolve_direct_download_url
    
    with mock.patch("requests.get", side_effect=Exception("offline fallback")):
        # 1. File link /u/
        url_u, name_u = resolve_direct_download_url("https://pixeldrain.com/u/xyz12345")
        assert "https://pixeldrain.com/api/file/xyz12345" in url_u
        assert name_u.endswith(".zip")
        
        # 2. List / Folder link /l/
        url_l, name_l = resolve_direct_download_url("https://pixeldrain.com/l/folder987")
        assert url_l == "https://pixeldrain.com/api/list/folder987/zip"
        assert name_l.endswith(".zip")
    print("[OK] Pixeldrain resolution tests passed!")

def test_extractor_diagnostics():
    print("Testing extractor diagnostics and multi-volume resolution...")
    import tempfile
    from pathlib import Path
    from extractor import classify_7z_error, find_primary_archive_volume
    
    # 1. Error classification
    err_pwd = classify_7z_error(2, "ERROR: Data Error in encrypted file. Wrong password?\nsub/foo.txt")
    assert "密码错误" in err_pwd
    
    err_space = classify_7z_error(2, "ERROR: There is not enough space on the disk.")
    assert "磁盘空间不足" in err_space
    
    err_corrupt = classify_7z_error(2, "ERROR: Can not open the file as archive")
    assert "文件损坏或格式不支持" in err_corrupt
    
    # 2. Multi-volume resolution
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        part1 = tmp_dir / "pack.part1.rar"
        part2 = tmp_dir / "pack.part2.rar"
        part1.write_text("dummy part 1")
        part2.write_text("dummy part 2")
        
        # When passed part 2, it should auto-locate part 1
        resolved, note = find_primary_archive_volume(part2)
        assert resolved.name == "pack.part1.rar"
        assert "已自动定位主卷" in note
        
        # When part 1 is missing, it reports failure to extract independently
        orphan_part = tmp_dir / "orphan.part2.rar"
        orphan_part.write_text("dummy orphan")
        _, orphan_note = find_primary_archive_volume(orphan_part)
        assert "无法独立解压" in orphan_note

    print("[OK] Extractor diagnostics tests passed!")

def test_archived_count_and_yearly_style():
    print("Testing yearly archive scanning and diff archived count consistency...")
    import tempfile
    from pathlib import Path
    from scanner import scan_author_directory
    from diff_engine import check_local_existence
    
    with tempfile.TemporaryDirectory() as td:
        author_dir = Path(td)
        # Create year folders 2021, 2022 with files
        (author_dir / "2021").mkdir()
        (author_dir / "2021" / "pic1.jpg").write_text("data")
        (author_dir / "2022").mkdir()
        (author_dir / "2022" / "pic2.jpg").write_text("data")
        
        data = scan_author_directory(author_dir)
        assert data["archive_style"] == "YEARLY"
        assert data["years"] == ["2021", "2022"]
        assert data["year_count"] == 2
        
        # Test existence check for year labels
        assert check_local_existence("2021", data)[0] == True
        assert check_local_existence("2022", data)[0] == True
        assert check_local_existence("2023", data)[0] == False

    print("[OK] Yearly archive and archived count consistency tests passed!")

if __name__ == "__main__":
    test_normalize_month()
    test_is_download_link()
    test_extract_password()
    test_heuristic_blacklist()
    test_check_local_existence()
    test_pixeldrain_resolution()
    test_extractor_diagnostics()
    test_archived_count_and_yearly_style()
    print("\nALL P1 FIXES TESTS PASSED! [DONE]")
