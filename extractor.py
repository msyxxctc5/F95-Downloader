import os
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from config import load_config

def get_7z_path() -> str:
    # Check default PATH first
    cmd = shutil.which("7z")
    if cmd:
        return cmd
    
    # Common Windows locations
    candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        r"C:\Program Files (x86)\AOMEI\AOMEI Backupper\6.10.0\7z.exe"
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "7z"

def extract_archive(archive_path: Path, output_dir: Path, passwords: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Extracts zip, rar, or 7z using 7z.exe with automatic password trying.
    """
    exe_7z = get_7z_path()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    cfg = load_config()
    pwds = []
    if passwords:
        pwds.extend(passwords)
    pwds.extend(cfg.get("known_passwords", ["f95zone", "f95"]))
    # Also try blank password
    pwds.append("")

    # Deduplicate while preserving order
    seen = set()
    unique_pwds = [p for p in pwds if not (p in seen or seen.add(p))]

    last_error = ""
    for pwd in unique_pwds:
        cmd = [
            exe_7z,
            "x",
            str(archive_path),
            f"-o{output_dir}",
            "-y",  # overwrite without prompt
            "-aoa" # overwrite all existing files
        ]
        if pwd:
            cmd.append(f"-p{pwd}")
        else:
            cmd.append("-p-")  # no password prompt

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode == 0:
                return True, f"Extracted successfully with password: {'(empty)' if not pwd else pwd}"
            else:
                last_error = result.stdout + "\n" + result.stderr
        except Exception as e:
            last_error = str(e)

    return False, f"Extraction failed. Details:\n{last_error}"

if __name__ == "__main__":
    print("7z executable path:", get_7z_path())
