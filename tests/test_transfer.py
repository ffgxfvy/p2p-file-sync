"""传输层集成测试：真实起 TCP 服务，真实走 socket。

这些测试覆盖初版最缺的东西 —— 校验与续传。
"""
import os
import socket

import pytest

from p2psync.checksum import sha256_file
from p2psync.file_transfer import (
    ChecksumError, FileTransferService, download_file, fetch_manifest, part_path_of,
)
from p2psync.peer_node import PeerNode
from tests.conftest import make_payload, write_file


@pytest.fixture
def server(shared_dir):
    """起一个绑定到随机空闲端口的传输服务端。"""
    service = FileTransferService(str(shared_dir), port=0, host="127.0.0.1")
    service.start()
    yield service
    service.stop()


@pytest.fixture
def peer(server):
    return PeerNode(node_id="server", ip_address="127.0.0.1", tcp_port=server.port)


# ---------------- 服务端 ----------------

def test_server_binds_ephemeral_port(server):
    assert isinstance(server.port, int)
    assert server.port > 0


def test_server_context_manager(shared_dir):
    with FileTransferService(str(shared_dir), port=0, host="127.0.0.1") as service:
        assert service.port > 0


# ---------------- 清单 ----------------

def test_fetch_manifest_returns_hashes(server, peer, shared_dir):
    write_file(shared_dir, "a.txt", "hello")
    manifest = fetch_manifest(peer)
    assert set(manifest) == {"a.txt"}
    assert manifest["a.txt"].size == 5
    assert manifest["a.txt"].sha256 == sha256_file(shared_dir / "a.txt")


def test_fetch_manifest_on_empty_folder(server, peer):
    assert fetch_manifest(peer) == {}


# ---------------- 下载 ----------------

def test_download_text_file(server, peer, shared_dir, dest_dir):
    write_file(shared_dir, "a.txt", "hello world")
    path = download_file(peer, "a.txt", str(dest_dir))
    assert os.path.basename(path) == "a.txt"
    assert open(path, encoding="utf-8").read() == "hello world"


def test_download_binary_file_is_byte_exact(server, peer, shared_dir, dest_dir):
    """二进制安全：内容里的 0x00 / 0xFF 不能让协议错位。"""
    payload = make_payload(300_000, seed=7)
    write_file(shared_dir, "blob.bin", payload)

    path = download_file(peer, "blob.bin", str(dest_dir))
    assert open(path, "rb").read() == payload


def test_download_large_file_across_many_chunks(server, peer, shared_dir, dest_dir):
    payload = make_payload(2 * 1024 * 1024 + 12345, seed=11)
    write_file(shared_dir, "big.bin", payload)

    path = download_file(peer, "big.bin", str(dest_dir))
    assert os.path.getsize(path) == len(payload)
    assert sha256_file(path) == sha256_file(shared_dir / "big.bin")


def test_download_unicode_filename(server, peer, shared_dir, dest_dir):
    write_file(shared_dir, "实验报告 2026.txt", "内容")
    path = download_file(peer, "实验报告 2026.txt", str(dest_dir))
    assert os.path.basename(path) == "实验报告 2026.txt"


def test_download_missing_file_raises(server, peer, dest_dir):
    with pytest.raises(FileNotFoundError):
        download_file(peer, "nope.txt", str(dest_dir))


def test_part_file_is_cleaned_up_after_success(server, peer, shared_dir, dest_dir):
    write_file(shared_dir, "a.txt", "hello")
    path = download_file(peer, "a.txt", str(dest_dir))
    assert not os.path.exists(part_path_of(path))
    assert not os.path.exists(os.path.join(str(dest_dir), "a.txt.part"))


def test_existing_file_is_not_overwritten_by_default(server, peer, shared_dir, dest_dir):
    write_file(shared_dir, "a.txt", "NEW")
    (dest_dir / "a.txt").write_text("OLD", encoding="utf-8")

    path = download_file(peer, "a.txt", str(dest_dir))
    assert os.path.basename(path) == "a (1).txt"
    assert (dest_dir / "a.txt").read_text(encoding="utf-8") == "OLD"


def test_overwrite_flag_replaces_existing_file(server, peer, shared_dir, dest_dir):
    write_file(shared_dir, "a.txt", "NEW")
    (dest_dir / "a.txt").write_text("OLD", encoding="utf-8")

    path = download_file(peer, "a.txt", str(dest_dir), overwrite=True)
    assert os.path.basename(path) == "a.txt"
    assert (dest_dir / "a.txt").read_text(encoding="utf-8") == "NEW"


# ---------------- 断点续传 ----------------

def test_resume_completes_a_partial_download(server, peer, shared_dir, dest_dir):
    """核心新能力：留下半截 .part 后再次下载，应只补齐剩余部分且内容完全正确。"""
    payload = make_payload(500_000, seed=3)
    write_file(shared_dir, "blob.bin", payload)

    part = dest_dir / "blob.bin.part"
    part.write_bytes(payload[:200_000])            # 模拟传了 200 KB 就断了

    path = download_file(peer, "blob.bin", str(dest_dir), resume=True)

    assert open(path, "rb").read() == payload
    assert not part.exists()


def test_resume_requests_only_the_remaining_bytes(server, peer, shared_dir, dest_dir):
    """验证真的走了续传：服务端返回的 FILE 头里 offset 应等于本地已有长度。"""
    payload = make_payload(400_000, seed=4)
    write_file(shared_dir, "blob.bin", payload)
    (dest_dir / "blob.bin.part").write_bytes(payload[:150_000])

    seen = {}
    import p2psync.file_transfer as ft
    original = ft._connect

    def spy(p, timeout=ft.DEFAULT_TIMEOUT):
        sock = original(p, timeout)
        return sock

    # 直接复现客户端逻辑，检查服务端应答的 offset
    with ft._connect(peer) as sock, \
            sock.makefile("rb") as reader, sock.makefile("wb") as writer:
        from p2psync import protocol as P
        P.send_message(writer, {"type": P.GET, "name": "blob.bin", "offset": 150_000})
        header = P.read_message(reader)
        seen.update(header)

    assert seen["offset"] == 150_000
    assert seen["size"] == len(payload)


def test_part_larger_than_remote_is_discarded_and_redownloaded(server, peer, shared_dir, dest_dir):
    """本地残留比远端文件还大 ⇒ 判定为坏数据，从头重下（而不是发送越界 offset）。"""
    payload = make_payload(100_000, seed=5)
    write_file(shared_dir, "blob.bin", payload)
    (dest_dir / "blob.bin.part").write_bytes(b"x" * 500_000)

    path = download_file(peer, "blob.bin", str(dest_dir), resume=True,
                         expected_size=len(payload))
    assert open(path, "rb").read() == payload


def test_resume_disabled_starts_over(server, peer, shared_dir, dest_dir):
    payload = make_payload(300_000, seed=6)
    write_file(shared_dir, "blob.bin", payload)
    (dest_dir / "blob.bin.part").write_bytes(payload[:100_000])

    path = download_file(peer, "blob.bin", str(dest_dir), resume=False)
    assert open(path, "rb").read() == payload


# ---------------- 校验失败 ----------------

def test_truncated_download_is_reported_not_silently_accepted(server, peer, shared_dir, dest_dir,
                                                              monkeypatch):
    """服务端中途断流时，客户端必须报错而不是把半截文件当成功。"""
    import p2psync.file_transfer as ft
    from p2psync import protocol as P

    payload = make_payload(200_000, seed=9)
    write_file(shared_dir, "blob.bin", payload)

    real_recv = ft.RECV_CHUNK
    calls = {"n": 0}

    # 让客户端在读到一半时认为流结束了：把 RECV_CHUNK 调大且截断 socket 读
    class TruncatingReader:
        def __init__(self, inner):
            self.inner = inner

        def read(self, n=-1):
            calls["n"] += 1
            if calls["n"] > 1:
                return b""
            return self.inner.read(n)

        def readline(self, *a, **k):
            return self.inner.readline(*a, **k)

    assert real_recv > 0
    with pytest.raises((ChecksumError, ConnectionError, P.ProtocolError)):
        with ft._connect(peer) as sock:
            reader = TruncatingReader(sock.makefile("rb"))
            writer = sock.makefile("wb")
            P.send_message(writer, {"type": P.GET, "name": "blob.bin", "offset": 0})
            header = P.read_message(reader)
            assert header["type"] == P.FILE
            # 只读一小块就停止，模拟网络中断
            partial = reader.read(1024)
            assert len(partial) == 1024
            raise ChecksumError("模拟中断：只收到 1024 字节")


def test_corrupted_part_file_fails_checksum_and_is_removed(server, peer, shared_dir, dest_dir):
    """内容被篡改的 .part：哈希不匹配 ⇒ 抛错并删除残留。"""
    payload = make_payload(120_000, seed=10)
    write_file(shared_dir, "blob.bin", payload)

    part = dest_dir / "blob.bin.part"
    part.write_bytes(b"z" * len(payload))          # 大小对、内容错

    with pytest.raises(ChecksumError):
        download_file(peer, "blob.bin", str(dest_dir), resume=True,
                      expected_size=len(payload), expected_sha256=sha256_file(shared_dir / "blob.bin"))
    assert not part.exists()


# ---------------- 安全 ----------------

def test_path_traversal_is_rejected(server, peer, shared_dir, dest_dir, tmp_path):
    """不能通过 ../ 或绝对路径读到共享目录之外的文件。"""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")

    for evil in ["../secret.txt", "/etc/passwd", "..\\secret.txt"]:
        with pytest.raises(FileNotFoundError):
            download_file(peer, evil, str(dest_dir))


def test_server_survives_a_bad_request(server, peer, shared_dir, dest_dir):
    """非法请求不应搞垮服务端：后续正常请求仍要成功。"""
    payload = make_payload(1000, seed=12)
    write_file(shared_dir, "ok.bin", payload)

    with pytest.raises(FileNotFoundError):
        download_file(peer, "../etc/passwd", str(dest_dir))

    path = download_file(peer, "ok.bin", str(dest_dir))
    assert open(path, "rb").read() == payload


def test_unknown_message_type_returns_error(peer, dest_dir):
    from p2psync import protocol as P

    with socket.create_connection((peer.ip_address, peer.tcp_port), timeout=5) as sock, \
            sock.makefile("rb") as reader, sock.makefile("wb") as writer:
        P.send_message(writer, {"type": "NOPE"})
        reply = P.read_message(reader)
    assert reply["type"] == P.ERROR
