"""命令行界面。"""
import argparse
import os
import sys
import time

from .controller import SyncController
from .sync_manager import FileSyncManager

BANNER = r"""
  ____        ____              _
 |  _ \      |  _ \ ___ _   _  | |__  _ __  _   _
 | |_) |_____| |_) / __| | | | | '_ \| '_ \| | | |
 |  __/_____|  __/\__ \ |_| | | |_) | | | | |_| |
 |_|        |_|   |___/\__, | |_.__/|_| |_|\__, |
                       |___/               |___/
       局域网 P2P 文件同步  ·  纯 Python 标准库
"""

HELP = """可用命令：
  list            查看已发现的设备
  plan [设备名]    预览同步计划（默认对全部在线设备）
  sync [设备名]    与设备同步（默认对全部在线设备）
  files           查看我的共享文件
  add <路径>       把文件加入共享目录
  info            显示本节点信息
  help            显示本帮助
  quit            退出
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="p2psync",
        description="局域网 P2P 文件同步（UDP 广播发现 + TCP 传输 + SHA-256 校验 + 断点续传）",
    )
    parser.add_argument("-d", "--dir", default="./shared_files",
                        help="共享目录（默认 ./shared_files）")
    parser.add_argument("-n", "--name", default=None, help="本节点名称")
    parser.add_argument("-p", "--port", type=int, default=0,
                        help="TCP 端口（默认 0 = 由系统分配）")
    parser.add_argument("--no-broadcast", action="store_true",
                        help="禁用 UDP 广播（只使用手动登记的节点）")
    parser.add_argument("--peers", default="",
                        help="手动指定节点，格式 ip:port 或 名称@ip:port，逗号分隔")
    parser.add_argument("--once", action="store_true",
                        help="启动后立即同步一次并退出（适合定时任务）")
    parser.add_argument("--wait", type=float, default=2.0,
                        help="--once 模式下等待发现节点的时间（秒）")
    return parser


def _register_manual_peers(controller, spec):
    for item in filter(None, (s.strip() for s in spec.split(","))):
        node_id, _, address = item.partition("@")
        if not address:
            node_id, address = address or item, item
        ip, _, port = address.rpartition(":")
        controller.discovery.register_peer(
            node_id=node_id or ip, ip_address=ip or address, tcp_port=int(port or 8888)
        )


def _targets(controller, name):
    peers = controller.online_peers()
    if not name:
        return peers
    match = {nid: p for nid, p in peers.items() if name in nid}
    return match


def _run_command(controller, line):
    parts = line.split()
    if not parts:
        return True
    command, args = parts[0].lower(), parts[1:]

    if command in ("quit", "exit", "q"):
        return False

    if command == "help":
        print(HELP)

    elif command == "list":
        peers = controller.known_peers
        if not peers:
            print("暂未发现设备。请确认对方也在运行，且处于同一网段。")
        for peer in peers.values():
            print(f"  {peer}")

    elif command == "info":
        print(f"  节点名称：{controller.node_id}")
        print(f"  TCP 端口：{controller.tcp_port}")
        print(f"  共享目录：{controller.shared_folder}")
        print(f"  共享文件：{len(controller.local_files())} 个")

    elif command == "files":
        files = controller.local_files()
        if not files:
            print("共享目录为空。用 `add <路径>` 添加文件。")
        for name, meta in files.items():
            print(f"  {name}  {meta.size} 字节  {meta.sha256[:12] or '(未计算哈希)'}")

    elif command == "add":
        if not args:
            print("用法：add <文件路径>")
        else:
            path = os.path.expanduser(args[0])
            if not os.path.isfile(path):
                print(f"文件不存在：{path}")
            else:
                target = controller.add_file(path)
                print(f"已加入共享：{target}")

    elif command in ("plan", "sync"):
        targets = _targets(controller, args[0] if args else None)
        if not targets:
            print("没有可同步的目标设备。")
        for node_id, peer in targets.items():
            try:
                if command == "plan":
                    plan, _ = controller.plan_for(peer)
                    print(f"\n[{node_id}]")
                    print("  " + plan.describe().replace("\n", "\n  "))
                else:
                    print(f"\n[{node_id}] 同步中…")
                    plan, results = controller.sync_with(peer)
                    if not plan.to_download:
                        print("  已是最新，无需下载。")
                    for name, outcome in results.items():
                        if isinstance(outcome, Exception):
                            print(f"  ✗ {name}：{outcome}")
                        else:
                            print(f"  ✓ {name} → {os.path.basename(outcome)}")
            except Exception as exc:                      # noqa: BLE001
                print(f"  ✗ 与 {node_id} 同步失败：{exc}")

    else:
        print(f"未知命令：{command}（输入 help 查看帮助）")

    return True


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.once:
        print(BANNER)

    controller = SyncController(
        shared_folder=args.dir,
        node_name=args.name,
        tcp_port=args.port,
        enable_broadcast=not args.no_broadcast,
    )
    controller.start()

    try:
        _register_manual_peers(controller, args.peers)

        print(f"✅ 节点已启动：{controller.node_id}  端口 {controller.tcp_port}")
        print(f"📁 共享目录：{controller.shared_folder}")

        if args.once:
            time.sleep(max(0.0, args.wait))
            outcome = controller.sync_all()
            total = 0
            for node_id, (plan, results) in outcome.items():
                downloaded = sum(1 for v in results.values() if not isinstance(v, Exception))
                total += downloaded
                print(f"  [{node_id}] 下载 {downloaded} 个文件"
                      + (f"，失败 {len(results) - downloaded} 个" if len(results) != downloaded else ""))
            if not outcome:
                print("  未发现在线设备。")
            print(f"本次共下载 {total} 个文件。")
            return 0

        print(HELP)
        while True:
            try:
                line = input("p2psync> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not _run_command(controller, line):
                break
        return 0
    finally:
        controller.stop()
        print("已退出。")


if __name__ == "__main__":      # pragma: no cover
    sys.exit(main())
