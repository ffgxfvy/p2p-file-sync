"""支持 `python -m p2psync`。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
