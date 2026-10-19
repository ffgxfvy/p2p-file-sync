"""线协议：JSON Lines 控制消息 + 裸字节文件块。

设计取舍
--------
控制消息用 **JSON Lines**（一行一个 JSON 对象，以 `\\n` 结束）而不是二进制打包：
- 可读性：用 `nc` / 串口调试工具就能看懂服务端在说什么，调试成本极低；
- 文件名可含中文与空格（JSON 负责转义，只要不含换行符即可）；
- 扩展新字段不需要改帧格式。

文件内容用**裸字节**紧跟消息尾部发送，长度由消息里的 `size` 字段给定。
这样避免了 base64 的 33% 膨胀，也不需要自己实现二进制分帧。

所有读写都基于 socket 的缓冲文件对象（`makefile`），
"读一行 → 读 N 字节 → 写一行 → 写 N 字节"的顺序严格交替，不存在粘包歧义。
"""
import json

# ---- 消息类型 ----
HELLO = "HELLO"                  # 节点上线广播

LIST = "LIST"                    # 请求文件清单
MANIFEST = "MANIFEST"            # 文件清单应答
GET = "GET"                      # 请求下载（可带 offset 断点续传）
FILE = "FILE"                    # 文件应答头（其后紧跟裸字节）
DONE = "DONE"                    # 该文件传输完成
ERROR = "ERROR"                  # 错误应答

ENCODING = "utf-8"
MAX_LINE_BYTES = 1024 * 1024     # 单条控制消息上限 1 MiB，防止恶意超长行


class ProtocolError(Exception):
    """对端发来的消息不符合协议约定。"""


def _json_default(obj):
    """允许把 Path / set 之类的对象直接塞进消息里。"""
    import pathlib
    if isinstance(obj, pathlib.Path):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"不可序列化的类型：{type(obj)!r}")


def encode(message):
    """把消息编码为一行字节（含结尾换行）。"""
    line = json.dumps(message, ensure_ascii=False, default=_json_default)
    if "\n" in line:
        raise ProtocolError("编码后的消息不得包含换行符")
    return (line + "\n").encode(ENCODING)


def send_message(writer, message):
    """发送一条控制消息并 flush（否则会卡在缓冲区里死等）。"""
    writer.write(encode(message))
    writer.flush()


def read_message(reader):
    """读取一条控制消息；对端关闭连接时返回 None。"""
    line = reader.readline(MAX_LINE_BYTES + 1)
    if not line:
        return None
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError("控制消息超长")
    try:
        message = json.loads(line.decode(ENCODING))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"无法解析控制消息：{exc}") from exc
    if not isinstance(message, dict) or "type" not in message:
        raise ProtocolError("控制消息必须是包含 type 字段的 JSON 对象")
    return message


def send_bytes(writer, data):
    writer.write(data)
    writer.flush()


def recv_exactly(reader, size):
    """从流里精确读取 size 字节；不足则抛错（避免把半截文件当成功）。"""
    if size <= 0:
        return b""
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = reader.read(min(remaining, 64 * 1024))
        if not chunk:
            raise ProtocolError(f"连接提前关闭：期望 {size} 字节，实际收到 {size - remaining} 字节")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def error(message):
    return {"type": ERROR, "message": str(message)}
