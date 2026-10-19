"""协议层测试：JSON Lines 编解码与精确读取。"""
import io
import json

import pytest

from p2psync import protocol as P


def test_encode_is_single_line_utf8():
    raw = P.encode({"type": P.LIST, "note": "中文 与 emoji 🚀"})
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1                 # 只有结尾那一个换行
    assert json.loads(raw.decode("utf-8"))["note"] == "中文 与 emoji 🚀"


def test_roundtrip_through_a_stream():
    buffer = io.BytesIO()
    P.send_message(buffer, {"type": P.GET, "name": "报表 2026.xlsx", "offset": 4096})
    P.send_message(buffer, {"type": P.DONE, "name": "报表 2026.xlsx"})
    buffer.seek(0)

    reader = io.BufferedReader(buffer)
    first = P.read_message(reader)
    second = P.read_message(reader)
    assert first["name"] == "报表 2026.xlsx"
    assert first["offset"] == 4096
    assert second["type"] == P.DONE
    assert P.read_message(reader) is None       # 读完返回 None，而不是抛异常


def test_embedded_newlines_are_escaped_not_emitted():
    """JSON 会把字符串里的换行转义成两个字符，因此不会破坏"一行一条消息"的约定。"""
    raw = P.encode({"type": P.LIST, "note": "line1\nline2"})
    assert raw.count(b"\n") == 1                # 只有结尾那一个真换行
    assert json.loads(raw.decode("utf-8"))["note"] == "line1\nline2"


def test_newline_in_a_field_survives_a_roundtrip():
    buffer = io.BytesIO()
    P.send_message(buffer, {"type": P.ERROR, "message": "第一行\n第二行"})
    buffer.seek(0)
    assert P.read_message(io.BufferedReader(buffer))["message"] == "第一行\n第二行"


def test_read_message_returns_none_on_closed_stream():
    assert P.read_message(io.BufferedReader(io.BytesIO(b""))) is None


def test_read_message_rejects_non_json():
    with pytest.raises(P.ProtocolError):
        P.read_message(io.BufferedReader(io.BytesIO(b"not json\n")))


def test_read_message_rejects_json_without_type():
    with pytest.raises(P.ProtocolError):
        P.read_message(io.BufferedReader(io.BytesIO(b'{"name": "a"}\n')))


def test_recv_exactly_reads_requested_bytes():
    reader = io.BufferedReader(io.BytesIO(b"0123456789"))
    assert P.recv_exactly(reader, 4) == b"0123"
    assert P.recv_exactly(reader, 6) == b"456789"


def test_recv_exactly_raises_on_truncated_stream():
    """这是"半截文件"必须报错而不是静默成功的关口。"""
    reader = io.BufferedReader(io.BytesIO(b"0123"))
    with pytest.raises(P.ProtocolError):
        P.recv_exactly(reader, 10)


def test_recv_exactly_zero_returns_empty():
    reader = io.BufferedReader(io.BytesIO(b"abc"))
    assert P.recv_exactly(reader, 0) == b""


def test_error_helper_shape():
    message = P.error("出错了")
    assert message == {"type": P.ERROR, "message": "出错了"}


def test_encode_handles_path_and_set():
    """Path / set 这类对象应能直接塞进消息（内部转成 str / 排序列表）。"""
    import pathlib
    raw = P.encode({"type": P.LIST, "path": pathlib.Path("a/b.txt"), "tags": {"y", "x"}})
    payload = json.loads(raw.decode("utf-8"))
    assert payload["tags"] == ["x", "y"]
    assert "b.txt" in payload["path"]
