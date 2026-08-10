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

# ---------- 下载（双路径 + 断点续传） ----------
if [ "$PLAT" = "windows" ]; then
  ASSET="aimake-${PLAT}-${ABI}.exe"
else
  ASSET="aimake-${PLAT}-${ABI}"
fi
if [ "$VERSION" = "latest" ]; then
  URL="${BASE_URL}/latest/download/${ASSET}"
  API_URL="https://api.github.com/repos/${REPO}/releases/latest"
else
  URL="${BASE_URL}/download/${VERSION}/${ASSET}"
  API_URL="https://api.github.com/repos/${REPO}/releases/tags/${VERSION}"
fi

DEST="${AIMAKE_INSTALL_DIR:-}"
if [ -z "$DEST" ]; then
  DEST="$HOME/.local/bin"
fi
mkdir -p "$DEST"

echo "→ 平台：${PLAT}-${ABI}"
echo "→ 下载：${URL}"

# 断点续传下载函数：-C - 支持中断恢复；--retry 处理瞬断
# 注意：-f 失败时不保留零字节占位；中断的断点文件保留供续传
dl() {
  curl -fL -C - --connect-timeout 15 --retry 3 --retry-delay 2 \
    --max-time 1800 -o "$DEST/aimake.bin" "$@"
}

# 路径 1：直连 release 下载（github.com → 302 → 存储 CDN）
if dl "$URL"; then
  : # 成功
else
  echo "→ 直连失败（网络受限），改用 GitHub API 下载…"
  # 路径 2：api.github.com（与直连不同的网络路径，部分受限网络可通）
  # 一次请求拿 Release JSON → awk 匹配资产名取 id（id 在 name 之前）
  RELEASE_JSON=$(curl -fsSL --connect-timeout 15 "$API_URL" 2>/dev/null) || true
  ASSET_ID=$(printf '%s\n' "$RELEASE_JSON" \
    | awk -v asset="$ASSET" '
        /"id":/ { id=$2; gsub(/[,"]/,"",id) }
        /"name":/ { name=$0; sub(/.*"name": *"/,"",name); sub(/".*/,"",name);
                    if (name==asset) { print id; exit } }')
  if [ -z "$ASSET_ID" ]; then
    echo "错误：Release 中找不到资产 $ASSET（API 也不可达）" >&2
    exit 1
  fi
  dl "https://api.github.com/repos/${REPO}/releases/assets/${ASSET_ID}" \
    -H "Accept: application/octet-stream" || {
      echo "错误：API 下载也失败" >&2; exit 1; }
fi

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
