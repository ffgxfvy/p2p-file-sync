#!/usr/bin/env python3
"""P2Psync 命令行入口。

用法：
    python main.py                          # 交互模式
    python main.py -d ./shared_files -n 笔记本A
    python main.py --peers 192.168.1.7:8888 --once   # 定时任务模式
"""
import sys

from p2psync.cli import main

if __name__ == "__main__":
    sys.exit(main())
