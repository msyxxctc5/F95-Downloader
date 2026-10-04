import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional

def find_idm_path() -> Optional[str]:
    cands = [
        shutil.which('IDMan.exe'),
        r'C:\Program Files (x86)\Internet Download Manager\IDMan.exe',
        r'C:\Program Files\Internet Download Manager\IDMan.exe',
        r'D:\Program Files (x86)\Internet Download Manager\IDMan.exe',
        r'D:\Program Files\Internet Download Manager\IDMan.exe'
    ]
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None

def download_with_idm(url: str, output_dir: Optional[str] = None, filename: Optional[str] = None) -> bool:
    """
    Sends download task directly to Internet Download Manager (IDM).
    Flags:
      /d URL  - URL to download
      /p path - Local path where the file will be saved
      /f file - Local file name
      /n      - Turn on quiet mode when IDMan starts
    """
    idm_exe = find_idm_path()
    if not idm_exe:
        return False

    if not output_dir:
        output_dir = os.path.expanduser(r"~\Downloads")

    cmd = [idm_exe, "/d", url, "/p", output_dir]
    if filename:
        cmd.extend(["/f", filename])
    cmd.append("/n")

    try:
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return True
    except Exception as e:
        return False

if __name__ == "__main__":
    p = find_idm_path()
    print("Found IDM executable:", p)
