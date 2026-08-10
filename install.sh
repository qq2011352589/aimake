#!/bin/sh
# aimake 一键安装脚本：检测 OS/架构 → 下载 GitHub Release 对应资产
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/qq2011352589/aimake/main/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- v0.1.0        # 指定版本
#
# 环境变量：
#   AIMAKE_INSTALL_DIR  安装目录（默认：Termux=$PREFIX/bin，其他=$HOME/.local/bin）
#   AIMAKE_REPO         仓库（默认 qq2011352589/aimake）
set -e

REPO="${AIMAKE_REPO:-qq2011352589/aimake}"
VERSION="${1:-latest}"
BASE_URL="https://github.com/${REPO}/releases"

# ---------- 平台检测 ----------
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
  Linux)  PLAT=linux ;;
  Darwin) PLAT=darwin ;;
  MINGW*|MSYS*|CYGWIN*) PLAT=windows ;;
  *) echo "错误：不支持的系统 $OS" >&2; exit 1 ;;
esac
case "$ARCH" in
  x86_64|amd64)  ABI=x86_64 ;;
  aarch64|arm64) ABI=aarch64 ;;
  armv7l|armhf)  ABI=armv7l ;;
  *) echo "错误：不支持的架构 $ARCH" >&2; exit 1 ;;
esac

# ---------- Termux 特例 ----------
# Android 用 bionic libc，跑不了 release 的 glibc 产物 → 提示本地编译
if [ -n "$PREFIX" ] && [ -d "$PREFIX/bin" ]; then
  echo "检测到 Termux（Android/bionic）：GitHub Release 产物为 glibc 版，无法在 Termux 运行。"
  echo "请在 Termux 本地编译（仓库已内置）："
  echo "  pkg install binutils patchelf ccache termux-elf-cleaner"
  echo "  pip install nuitka && python -m nuitka --standalone --onefile main.py"
  echo "  ./main.bin scan"
  exit 1
fi

# ---------- 下载 ----------
if [ "$PLAT" = "windows" ]; then
  ASSET="aimake-${PLAT}-${ABI}.exe"
else
  ASSET="aimake-${PLAT}-${ABI}"
fi
if [ "$VERSION" = "latest" ]; then
  URL="${BASE_URL}/latest/download/${ASSET}"
else
  URL="${BASE_URL}/download/${VERSION}/${ASSET}"
fi

DEST="${AIMAKE_INSTALL_DIR:-}"
if [ -z "$DEST" ]; then
  DEST="$HOME/.local/bin"
fi
mkdir -p "$DEST"

echo "→ 平台：${PLAT}-${ABI}"
echo "→ 下载：${URL}"
curl -fsSL "$URL" -o "$DEST/aimake"
chmod +x "$DEST/aimake"

echo "→ 安装完成：$DEST/aimake"
echo "→ 验证："
"$DEST/aimake" --help | head -1
echo "（PATH 不含 $DEST 时：export PATH=\"\$PATH:$DEST\"）"
