"""文件校验：用 SHA-256 判断"内容是否一致"，而不是靠大小 + 修改时间。

为什么必须换成哈希：
- 大小 + mtime 是**元数据**，内容不同但大小相同（甚至 mtime 相同）的文件会被漏判；
- 传输中断产生的半截文件，大小可能恰好等于原文件；
- 断点续传的正确性完全依赖"能否验证拼装后的完整内容"。
"""
import hashlib
import os

CHUNK_SIZE = 1024 * 256        # 256 KiB


def sha256_file(path, chunk_size=CHUNK_SIZE):
    """计算文件的 SHA-256（十六进制小写）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_stream(iterable, chunk_size=CHUNK_SIZE):
    """对字节流计算 SHA-256，用于校验接收中的数据。"""
    h = hashlib.sha256()
    for chunk in iterable:
        if not chunk:
            continue
        h.update(chunk)
    return h.hexdigest()


def sha256_of_bytes(data):
    return hashlib.sha256(data).hexdigest()


def file_size(path):
    return os.path.getsize(path)


def verify_file(path, expected_sha256):
    """校验文件内容；文件不存在或不匹配都返回 False。"""
    if not path or not os.path.isfile(path):
        return False
    try:
        return sha256_file(path) == expected_sha256
    except OSError:
        return False
