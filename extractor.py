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

import uuid
import time

def extract_archive(archive_path: Path, output_dir: Path, passwords: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Extracts zip, rar, or 7z using 7z.exe with automatic password trying.
    Extracts to a temporary staging folder first to avoid leaving empty or partial directories on failure.
    """
    exe_7z = get_7z_path()
    
    # Create temporary staging directory in the same parent folder (for fast atomic rename across the same drive)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir.parent / f".partial_extract_{output_dir.name}_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
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
    success = False
    used_pwd = ""

    try:
        for pwd in unique_pwds:
            cmd = [
                exe_7z,
                "x",
                str(archive_path),
                f"-o{temp_dir}",
                "-y",  # overwrite without prompt
                "-aoa", # overwrite all existing files
                "-sccUTF-8" # force UTF-8 console output for non-ASCII filenames
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
                    encoding="utf-8",
                    errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.returncode == 0:
                    # Check that temp_dir actually contains files
                    has_files = any(temp_dir.iterdir())
                    if has_files:
                        success = True
                        used_pwd = pwd
                        break
                    else:
                        last_error = "解压成功但解压出的文件夹为空"
                else:
                    last_error = result.stdout + "\n" + result.stderr
            except Exception as e:
                last_error = str(e)

        if success:
            # Promote temp_dir to output_dir
            if not output_dir.exists():
                os.replace(temp_dir, output_dir)
            else:
                # Merge contents into existing output_dir
                for item in temp_dir.iterdir():
                    dest_item = output_dir / item.name
                    if dest_item.exists():
                        if dest_item.is_dir():
                            shutil.rmtree(dest_item, ignore_errors=True)
                        else:
                            dest_item.unlink(missing_ok=True)
                    shutil.move(str(item), str(output_dir))
                shutil.rmtree(temp_dir, ignore_errors=True)
            return True, f"解压成功 (使用密码: {'[空密码]' if not used_pwd else used_pwd})"
        else:
            # Clean up failed temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False, f"解压失败: {last_error}"
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False, f"解压异常: {str(e)}"

if __name__ == "__main__":
    print("7z executable path:", get_7z_path())
