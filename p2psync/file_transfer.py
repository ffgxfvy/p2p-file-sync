"""TCP 文件传输：分块收发 + SHA-256 校验 + 断点续传。

相对初版的三处关键改动
----------------------
1. **完整性校验**：每个文件都带 SHA-256，客户端在收完后校验全量哈希才落盘为正式文件。
   初版只比较"大小 + 修改时间"，半截文件同样大小就可能被当成传输成功。
2. **断点续传**：传输写到 `<name>.part`，中断后保留现场；下次同步读取 `.part` 的实际长度
   作为 `offset` 请求续传，服务端从该偏移继续发送。校验通过后才改名为正式文件。
3. **并发传输**：客户端用线程池同时下载多个文件（服务端每个连接一个线程）。
"""
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import protocol as P
from .checksum import sha256_file, file_size
from .sync_manager import PART_SUFFIX, FileMeta
DEFAULT_TIMEOUT = 10.0
RECV_CHUNK = 64 * 1024


def part_path_of(dest_path):
    return dest_path + PART_SUFFIX


# ======================================================================
# 服务端
# ======================================================================

class FileTransferService:
    """提供文件清单查询与文件下载的 TCP 服务端。"""

    def __init__(self, shared_folder, port=8888, host="0.0.0.0", timeout=DEFAULT_TIMEOUT):
        self.shared_folder = shared_folder
        self.host = host
        self.requested_port = port
        self.port = port                   # 绑定后会被替换为真实端口
        self.timeout = timeout
        self._server = None
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self.request_count = 0

    # ------------- 生命周期 -------------

    def start(self):
        """启动监听。port=0 时由系统分配空闲端口（测试用）。"""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.requested_port))
        self.port = self._server.getsockname()[1]
        self._server.listen(16)
        self._server.settimeout(0.5)       # 便于 stop() 时能退出 accept
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._running = False
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ------------- 请求处理 -------------

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_client, args=(conn, addr), daemon=True
            ).start()

    def _handle_client(self, conn, addr):
        conn.settimeout(self.timeout)
        try:
            with conn, conn.makefile("rb") as reader, conn.makefile("wb") as writer:
                while True:
                    message = P.read_message(reader)
                    if message is None:
                        return
                    with self._lock:
                        self.request_count += 1
                    msg_type = message["type"]
                    if msg_type == P.LIST:
                        self._serve_manifest(writer)
                    elif msg_type == P.GET:
                        if not self._serve_file(writer, message):
                            return
                    else:
                        P.send_message(writer, P.error(f"不支持的消息类型：{msg_type}"))
        except (OSError, P.ProtocolError):
            return

    def _serve_manifest(self, writer):
        manifest = self._scan()
        P.send_message(writer, {
            "type": P.MANIFEST,
            "files": {name: meta.to_dict() for name, meta in manifest.items()},
        })

    def _serve_file(self, writer, message):
        """发送文件头 + 从 offset 开始的裸字节 + DONE。"""
        name = message.get("name")
        offset = int(message.get("offset", 0) or 0)
        path = os.path.join(self.shared_folder, name or "")

        # 安全：只允许共享目录内的**普通文件**，拒绝路径穿越
        if not name or os.path.basename(name) != name or not os.path.isfile(path):
            P.send_message(writer, P.error(f"文件不存在或非法：{name}"))
            return False

        size = file_size(path)
        if offset < 0 or offset > size:
            offset = 0                      # 偏移越界则从头传（客户端会重新校验）
        digest = sha256_file(path)

        P.send_message(writer, {
            "type": P.FILE, "name": name, "size": size,
            "sha256": digest, "offset": offset,
        })

        remaining = size - offset
        with open(path, "rb") as f:
            f.seek(offset)
            sent = 0
            while sent < remaining:
                chunk = f.read(min(RECV_CHUNK, remaining - sent))
                if not chunk:
                    break
                writer.write(chunk)
                sent += len(chunk)
            writer.flush()

        P.send_message(writer, {"type": P.DONE, "name": name, "size": size, "sha256": digest})
        return True

    def _scan(self):
        from .sync_manager import FileSyncManager

        return FileSyncManager(self.shared_folder).get_metadata()


# ======================================================================
# 客户端
# ======================================================================

def _connect(peer, timeout=DEFAULT_TIMEOUT):
    sock = socket.create_connection((peer.ip_address, peer.tcp_port), timeout=timeout)
    sock.settimeout(timeout)
    return sock


def fetch_manifest(peer, timeout=DEFAULT_TIMEOUT):
    """拉取远端文件清单，返回 {文件名: FileMeta}。"""
    with _connect(peer, timeout) as sock, \
            sock.makefile("rb") as reader, sock.makefile("wb") as writer:
        P.send_message(writer, {"type": P.LIST})
        message = P.read_message(reader)
        if message is None:
            raise ConnectionError(f"{peer} 未返回清单就关闭了连接")
        if message["type"] == P.ERROR:
            raise ConnectionError(message.get("message", "远端返回错误"))
        if message["type"] != P.MANIFEST:
            raise P.ProtocolError(f"期望 MANIFEST，收到 {message['type']}")
        return {name: FileMeta.from_dict(d) for name, d in message["files"].items()}


def download_file(peer, name, dest_dir, expected_sha256=None, expected_size=None,
                  resume=True, timeout=DEFAULT_TIMEOUT, overwrite=False):
    """下载单个文件，支持断点续传与 SHA-256 校验。

    返回最终落盘路径。校验不通过会抛 `ChecksumError`，并保留 `.part` 以便续传。
    """
    os.makedirs(dest_dir, exist_ok=True)
    tentative = os.path.join(dest_dir, name)
    part_path = part_path_of(tentative)

    offset = 0
    if resume and os.path.isfile(part_path):
        offset = file_size(part_path)
        # 本地残留已比远端完整文件还大 ⇒ 说明是坏数据，删除重下
        if expected_size is not None and offset > expected_size:
            os.remove(part_path)
            offset = 0

    with _connect(peer, timeout) as sock, \
            sock.makefile("rb") as reader, sock.makefile("wb") as writer:

        P.send_message(writer, {"type": P.GET, "name": name, "offset": offset})
        header = P.read_message(reader)
        if header is None:
            raise ConnectionError(f"{peer} 未返回文件头")
        if header["type"] == P.ERROR:
            raise FileNotFoundError(header.get("message", f"远端无此文件：{name}"))
        if header["type"] != P.FILE:
            raise P.ProtocolError(f"期望 FILE，收到 {header['type']}")

        total = int(header["size"])
        remote_sha = header.get("sha256") or expected_sha256
        start = int(header.get("offset", 0))
        if start != offset:
            # 服务端调整了偏移（越界保护），本地必须跟着重置，否则内容会错位
            if os.path.exists(part_path):
                os.remove(part_path)
            offset = start

        mode = "r+b" if os.path.isfile(part_path) else "wb"
        with open(part_path, mode) as f:
            if mode == "r+b":
                f.seek(offset)
                f.truncate(offset)
            else:
                offset = 0
            remaining = total - offset
            received = 0
            while received < remaining:
                chunk = reader.read(min(RECV_CHUNK, remaining - received))
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)
            f.flush()

        trailer = P.read_message(reader)
        if trailer is None or trailer["type"] not in (P.DONE, P.ERROR):
            raise P.ProtocolError("传输未正常结束（缺少 DONE）")

    # ---- 校验 ----
    actual_size = file_size(part_path)
    if actual_size != total:
        raise ChecksumError(
            f"大小不符：期望 {total} 字节，实际 {actual_size} 字节（已保留 .part 可续传）"
        )

    digest = sha256_file(part_path)
    if remote_sha and digest != remote_sha:
        os.remove(part_path)               # 内容坏了，续传无意义
        raise ChecksumError(f"SHA-256 校验失败：期望 {remote_sha[:12]}…，实际 {digest[:12]}…")

    # ---- 落盘 ----
    final_path = tentative
    if os.path.exists(final_path) and not overwrite:
        base, ext = os.path.splitext(name)
        index = 1
        while os.path.exists(final_path):
            final_path = os.path.join(dest_dir, f"{base} ({index}){ext}")
            index += 1
    os.replace(part_path, final_path)
    return final_path


def download_many(peer, names, dest_dir, manifest=None, max_workers=4, **kwargs):
    """并发下载多个文件，返回 {文件名: 结果或异常}。"""
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for name in names:
            meta = manifest.get(name) if manifest else None
            futures[pool.submit(
                download_file, peer, name, dest_dir,
                expected_sha256=meta.sha256 if meta else None,
                expected_size=meta.size if meta else None,
                **kwargs
            )] = name
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:                  # noqa: BLE001 - 汇总给调用方
                results[name] = exc
    return results


class ChecksumError(Exception):
    """接收内容与远端声明的哈希不一致。"""
