"""pytest 公共 fixture。"""
import os
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

for _name in ("stdout", "stderr"):
    _stream = getattr(sys, _name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


@pytest.fixture
def shared_dir(tmp_path):
    """一个作为共享目录的临时文件夹。"""
    folder = tmp_path / "shared"
    folder.mkdir()
    return folder


@pytest.fixture
def dest_dir(tmp_path):
    folder = tmp_path / "dest"
    folder.mkdir()
    return folder


def write_file(folder, name, content):
    """写入测试文件（content 为 bytes 时原样写入）。"""
    path = pathlib.Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)
    return path


def make_payload(size, seed=0):
    """生成可复现的伪随机二进制内容（用于测试二进制安全）。"""
    import random

    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(size))
