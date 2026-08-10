"""aimake 独立可执行入口（Nuitka 编译用）。

用法（Termux）：
    python -m pip install nuitka
    pkg install patchelf ccache binutils ldd termux-elf-cleaner
    python -m nuitka --standalone --onefile main.py
"""

import sys

from aimake.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
