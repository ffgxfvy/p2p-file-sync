#!/usr/bin/env python3
"""两节点端到端演示：不需要第二台设备，在本机内存里起两个节点。

    python examples/two_node_demo.py

流程：A 造文件 → B 发现 A → B 拉取 → 校验 → 改动 A 的文件 → B 再拉一次。
"""
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from p2psync import SyncController                    # noqa: E402
from p2psync.checksum import sha256_file              # noqa: E402


def line(title=""):
    print(("- " + title) if title else "-" * 66)


def main():
    workdir = tempfile.mkdtemp(prefix="p2psync-demo-")
    print(f"工作目录：{workdir}\n")

    dir_a = os.path.join(workdir, "A")
    dir_b = os.path.join(workdir, "B")
    os.makedirs(dir_a, exist_ok=True)
    os.makedirs(dir_b, exist_ok=True)

    # 两个节点都关闭 UDP 广播，改为显式登记 —— 这样演示是确定性的
    node_a = SyncController(dir_a, node_name="node-A", enable_broadcast=False).start()
    node_b = SyncController(dir_b, node_name="node-B", enable_broadcast=False).start()

    try:
        line("1. A 准备共享文件")
        with open(os.path.join(dir_a, "readme.txt"), "w", encoding="utf-8") as f:
            f.write("来自 A 的问候。\n")
        with open(os.path.join(dir_a, "data.bin"), "wb") as f:
            f.write(bytes(range(256)) * 800)          # 200 KB 二进制
        for name, meta in node_a.local_files().items():
            print(f"   {name:<12} {meta.size:>8} 字节  sha256={meta.sha256[:12]}…")

        line("2. B 发现 A 并计算同步计划")
        peer_a = node_b.discovery.register_peer("node-A", "127.0.0.1", node_a.tcp_port)
        print(f"   发现节点：{peer_a}")
        plan, _ = node_b.plan_for(peer_a)
        print("   " + plan.describe().replace("\n", "\n   "))

        line("3. B 执行同步")
        plan, results = node_b.sync_with(peer_a)
        for name, outcome in sorted(results.items()):
            if isinstance(outcome, Exception):
                print(f"   ✗ {name}：{outcome}")
            else:
                print(f"   ✓ {name} → {os.path.basename(outcome)}")

        line("4. 校验：两端内容逐字节一致")
        for name in ("readme.txt", "data.bin"):
            hash_a = sha256_file(os.path.join(dir_a, name))
            hash_b = sha256_file(os.path.join(dir_b, name))
            flag = "一致" if hash_a == hash_b else "不一致"
            print(f"   {name:<12} {flag}  {hash_b[:16]}…")

        line("5. 再同步一次（应无事可做）")
        plan, results = node_b.sync_with(peer_a)
        print("   计划：" + plan.describe().replace("\n", "\n   "))
        print(f"   下载结果：{results or '（空）'}")

        line("6. 改动 A 的文件（内容变了、大小不变）后再同步")
        with open(os.path.join(dir_a, "readme.txt"), "w", encoding="utf-8") as f:
            f.write("A 改了内容，但字节数一样。\n")
        plan, _ = node_b.plan_for(peer_a)
        print("   计划：" + plan.describe().replace("\n", "\n   "))
        print("   → 大小相同、mtime 不同，只有比哈希才能发现内容变了")

        line("7. 模拟断点续传")
        final = node_b.sync_manager.path_of("data.bin")
        part = final + ".part"

        # 先让 B 侧确实没有这个文件，再预置半截数据，才能逼出真正的续传路径
        for leftover in (final, part):
            if os.path.exists(leftover):
                os.remove(leftover)

        payload = open(os.path.join(dir_a, "data.bin"), "rb").read()
        with open(part, "wb") as f:
            f.write(payload[:50_000])                 # 只留 50 KB
        print(f"   预置半截文件：{os.path.basename(part)}"
              f"（{os.path.getsize(part)} 字节）  /  远端 {len(payload)} 字节")

        plan, results = node_b.sync_with(peer_a)
        indent = plan.describe().replace(chr(10), chr(10) + "   ")
        print(f"   计划：{indent}")
        size_ok = os.path.getsize(final) == len(payload)
        hash_ok = sha256_file(final) == sha256_file(os.path.join(dir_a, "data.bin"))
        print(f"   续传完成：{os.path.getsize(final)} 字节"
              f"  大小{'正确' if size_ok else '错误'}"
              f"  哈希{'匹配' if hash_ok else '不匹配'}")
        print(f"   .part 已清理：{not os.path.exists(part)}")

        line("演示结束")
    finally:
        node_a.stop()
        node_b.stop()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main() or 0)
