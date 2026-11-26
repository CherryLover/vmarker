# ============================================================================
#  media —— 下载用的「带封面成片」：把封面塞进 mp4（attached_pic / covr）
#
#  只重新封装不重新编码（-c copy），ffmpeg 流式读写，内存不随文件变大。
#  按需生成、落盘缓存：比原片和封面都新就直接复用，任何一方更新就重做。
#  原片自带的封面一律丢掉换成平台封面，只留 1 条 attached_pic。
#  在线播放仍走原片；生成失败退回原片，下载永远不坏。
# ============================================================================
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path

import imageio_ffmpeg

log = logging.getLogger(__name__)
_locks: dict[Path, asyncio.Lock] = {}  # 同一文件同时只生成一次（单进程部署）


def _fresh(dest: Path, *sources: Path) -> bool:
    return dest.is_file() and all(dest.stat().st_mtime >= s.stat().st_mtime for s in sources)


async def _run(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        imageio_ffmpeg.get_ffmpeg_exe(),
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    return proc.returncode or 0, err.decode(errors="replace")


async def _real_videos(video: Path) -> int:
    """数一数真正的视频轨（不含原有封面）。只读文件头，很快。"""
    _, info = await _run("-hide_banner", "-i", str(video))
    return sum("Video:" in ln and "(attached pic)" not in ln for ln in info.splitlines() if "Stream #" in ln)


async def _mux(video: Path, cover: Path, dest: Path) -> bool:
    # 0:V（大写）排除原片自带的封面：已有 covr 时是「替换」而不是多写一条 mjpeg 轨
    # 新封面排在所有真视频轨之后，所以它的视频序号 = 真视频轨数量
    tmp = dest.with_name(f".{dest.name}.part")
    pic = f"-disposition:v:{await _real_videos(video)}"
    code, err = await _run(
        "-v", "error", "-y", "-i", str(video), "-i", str(cover),
        "-map", "0:V", "-map", "0:a?", "-map", "1", "-c", "copy", pic, "attached_pic", "-f", "mp4", str(tmp),
    )  # fmt: skip
    if code:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        log.warning("封面写入失败，退回原片 %s: %s", video, err[-500:])
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
