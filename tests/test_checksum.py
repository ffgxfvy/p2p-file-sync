"""SHA-256 校验模块测试。"""
import os

import pytest

from p2psync.checksum import (
    sha256_file, sha256_of_bytes, sha256_stream, verify_file, file_size,
)

KNOWN_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
KNOWN_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_empty_file_hash(shared_dir):
    path = shared_dir / "empty.bin"
    path.write_bytes(b"")
    assert sha256_file(path) == KNOWN_EMPTY


def test_known_vector(shared_dir):
    path = shared_dir / "abc.txt"
    path.write_bytes(b"abc")
    assert sha256_file(path) == KNOWN_ABC
    assert sha256_of_bytes(b"abc") == KNOWN_ABC


def test_large_file_is_hashed_in_chunks(shared_dir):
    """跨多个读取块的大文件哈希必须正确（分块读取不能漏字节）。"""
    payload = bytes(range(256)) * 4096          # 1 MiB
    path = shared_dir / "big.bin"
    path.write_bytes(payload)
    assert sha256_file(path, chunk_size=1024) == sha256_of_bytes(payload)
    assert file_size(path) == len(payload)


def test_verify_file_accepts_match_and_rejects_mismatch(shared_dir):
    path = shared_dir / "f.txt"
    path.write_text("hello", encoding="utf-8")
    good = sha256_file(path)
    assert verify_file(path, good) is True
    assert verify_file(path, "0" * 64) is False


def test_verify_file_returns_false_for_missing_path(tmp_path):
    assert verify_file(tmp_path / "nope.txt", "0" * 64) is False
    assert verify_file(None, "0" * 64) is False


def test_sha256_stream_matches_file_hash(shared_dir):
    payload = os.urandom(5000)
    path = shared_dir / "s.bin"
    path.write_bytes(payload)
    chunks = [payload[i:i + 777] for i in range(0, len(payload), 777)]
    assert sha256_stream(chunks) == sha256_file(path)
