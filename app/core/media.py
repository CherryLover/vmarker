# ============================================================================
#  media —— 下载用的「带封面成片」：把封面塞进 mp4（attached_pic / covr）
#
#  只重新封装不重新编码（-c copy），ffmpeg 流式读写，内存不随文件变大。
#  按需生成、落盘缓存：比原片和封面都新就直接复用，任何一方更新就重做。
#  在线播放仍走原片；生成失败退回原片，下载永远不坏。
# ============================================================================
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import imageio_ffmpeg

log = logging.getLogger(__name__)
_locks: dict[Path, asyncio.Lock] = {}  # 同一文件同时只生成一次（单进程部署）


def _fresh(dest: Path, *sources: Path) -> bool:
    return dest.is_file() and all(dest.stat().st_mtime >= s.stat().st_mtime for s in sources)


async def _mux(video: Path, cover: Path, dest: Path) -> bool:
    tmp = dest.with_name(f".{dest.name}.part")
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(video), "-i", str(cover)]
    cmd += ["-map", "0", "-map", "1", "-c", "copy", "-disposition:v:1", "attached_pic", "-f", "mp4", str(tmp)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode:
        tmp.unlink(missing_ok=True)
        log.warning("封面写入失败，退回原片 %s: %s", video, err.decode(errors="replace")[-500:])
        return False
    os.replace(tmp, dest)
    return True


async def with_cover(video: Path, cover: Path | None, dest: Path) -> Path:
    """返回下载该用的文件：有封面 → 带封面的缓存副本；没有或失败 → 原片。"""
    if not cover:
        return video
    async with _locks.setdefault(dest, asyncio.Lock()):
        if _fresh(dest, video, cover) or await _mux(video, cover, dest):
            return dest
    return video
