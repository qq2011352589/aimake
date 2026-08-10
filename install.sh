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
  armv7l|armhf)  ABI=arm ;;
  i686)          ABI=i686 ;;
  *) echo "错误：不支持的架构 $ARCH" >&2; exit 1 ;;
esac

# ---------- Termux 特例 ----------
# Android 用 bionic libc，GitHub Release 的 glibc 产物无法运行
# → 改为下载 Termux 专用资产（aimake-termux-<arch>，由 CI 在 termux-docker 容器内编译）
# 安装目录默认 $PREFIX/bin（其余平台默认 $HOME/.local/bin）
if [ -n "$PREFIX" ] && [ -d "$PREFIX/bin" ]; then
  PLAT=termux
  if [ -z "$AIMAKE_INSTALL_DIR" ]; then
    AIMAKE_INSTALL_DIR="$PREFIX/bin"
  fi
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
curl -fsSL "$URL" -o "$DEST/aimake.bin"
chmod +x "$DEST/aimake.bin"

# Termux：无静态 libpython → bionic 产物依赖 libpython3.14.so
# 生成启动器（内置 LD_LIBRARY_PATH 定位 $PREFIX/lib 下的 libpython）
if [ "$PLAT" = "termux" ]; then
  cat > "$DEST/aimake" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
SELF="$(dirname "$(readlink -f "$0")")/aimake.bin"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}${PREFIX:-/data/data/com.termux/files/usr}/lib"
exec "$SELF" "$@"
EOF
  chmod +x "$DEST/aimake"
else
  mv "$DEST/aimake.bin" "$DEST/aimake"
fi

echo "→ 安装完成：$DEST/aimake"
echo "→ 验证："
"$DEST/aimake" --help | head -1
echo "（PATH 不含 $DEST 时：export PATH=\"\$PATH:$DEST\"）"
