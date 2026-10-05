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
import re

def find_primary_archive_volume(archive_path: Path) -> Tuple[Path, Optional[str]]:
    """
    Detects if the given archive file is a secondary multi-volume split (e.g., .part2.rar, .002, .r00).
    If so, attempts to locate the primary first volume (.part1.rar, .001, .rar).
    Returns: (resolved_path, notice_message)
    """
    p = Path(archive_path)
    parent = p.parent
    name = p.name

    # Case 1: .part2.rar, .part02.rar, .part2.zip, etc.
    m_part = re.search(r'^(.*?)\.part0*([2-9]|\d{2,})\.(rar|zip|7z)$', name, re.I)
    if m_part:
        base, _, ext = m_part.group(1), m_part.group(2), m_part.group(3)
        for p1_name in (f"{base}.part1.{ext}", f"{base}.part01.{ext}", f"{base}.part001.{ext}"):
            cand = parent / p1_name
            if cand.exists():
                return cand, f"检测到分卷压缩包，已自动定位主卷: {cand.name}"
        return p, f"检测到分卷文件 {name}，但在目录中未找到第一分卷 (.part1.{ext})，无法独立解压"

    # Case 2: .002, .003 (split 7z/zip/raw)
    m_num = re.search(r'^(.*?)\.0*([2-9]|\d{2,})$', name, re.I)
    if m_num:
        base = m_num.group(1)
        for p1_name in (f"{base}.001", f"{base}.01", f"{base}.1"):
            cand = parent / p1_name
            if cand.exists():
                return cand, f"检测到数值分卷，已自动定位主分卷: {cand.name}"
        return p, f"检测到分卷文件 {name}，但在目录中未找到第一分卷 ({base}.001)，无法独立解压"

    # Case 3: .r00, .r01 (legacy RAR)
    m_r = re.search(r'^(.*?)\.r\d{2}$', name, re.I)
    if m_r:
        base = m_r.group(1)
        cand = parent / f"{base}.rar"
        if cand.exists():
            return cand, f"检测到旧版 RAR 分卷，已自动定位主卷: {cand.name}"
        return p, f"检测到旧版分卷文件 {name}，但在目录中未找到主卷 ({base}.rar)，无法独立解压"

    return p, None

def classify_7z_error(returncode: int, output: str) -> str:
    """
    Classifies 7-Zip process failure into human-readable diagnosed error messages.
    """
    lowered = output.lower()
    if "wrong password" in lowered or "data error in encrypted file" in lowered:
        return "密码错误：提供的密码均无法解开此加密压缩包"
    if "there is not enough space on the disk" in lowered or "no space left on device" in lowered:
        return "磁盘空间不足：目标磁盘无足够可用空间以完成解压"
    if "can not open the file as archive" in lowered or "cannot open the file as archive" in lowered:
        return "文件损坏或格式不支持：无法作为有效压缩包打开（文件可能未下载完整或非标准格式）"
    if returncode == 8:
        return "内存不足：7-Zip 运行解压过程耗尽系统内存"
    if returncode == 7:
        return "命令行语法错误：传递给 7-Zip 的参数异常"
    if returncode == 2:
        return f"7-Zip 致命错误 (ExitCode 2): {output.strip()}"
    return f"7-Zip 执行异常 (ExitCode {returncode}): {output.strip()}"

def _recursive_merge_dir(src_dir: Path, dst_dir: Path):
    """
    Recursively moves files from src_dir into dst_dir, overwriting existing files
    without destroying existing non-conflicting files in destination subdirectories.
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        dest_item = dst_dir / item.name
        if item.is_dir():
            _recursive_merge_dir(item, dest_item)
        else:
            if dest_item.exists():
                dest_item.unlink(missing_ok=True)
            shutil.move(str(item), str(dest_item))

def extract_archive(archive_path: Path, output_dir: Path, passwords: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Extracts zip, rar, or 7z using 7z.exe with automatic password trying and multi-volume resolution.
    Extracts to a temporary staging folder first to avoid leaving empty or partial directories on failure.
    """
    exe_7z = get_7z_path()
    
    # 1. Multi-volume check and primary volume auto-resolution
    resolved_path, vol_notice = find_primary_archive_volume(archive_path)
    if vol_notice and "无法独立解压" in vol_notice:
        return False, f"分卷缺失: {vol_notice}"
    archive_path = resolved_path

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
                    output_text = (result.stdout or "") + "\n" + (result.stderr or "")
                    err_desc = classify_7z_error(result.returncode, output_text)
                    last_error = err_desc
                    # If fatal non-password error (e.g. broken file or disk full), abort trying other passwords
                    if "磁盘空间不足" in err_desc or "文件损坏或格式不支持" in err_desc:
                        break
            except Exception as e:
                last_error = str(e)

        if success:
            # Promote temp_dir to output_dir
            if not output_dir.exists():
                os.replace(temp_dir, output_dir)
            else:
                # Merge contents recursively into existing output_dir without destroying non-conflicting subfolders
                _recursive_merge_dir(temp_dir, output_dir)
                shutil.rmtree(temp_dir, ignore_errors=True)
            note = f" (附: {vol_notice})" if vol_notice else ""
            return True, f"解压成功 (使用密码: {'[空密码]' if not used_pwd else used_pwd}){note}"
        else:
            # Clean up failed temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False, f"解压失败: {last_error}"
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False, f"解压异常: {str(e)}"

if __name__ == "__main__":
    print("7z executable path:", get_7z_path())
