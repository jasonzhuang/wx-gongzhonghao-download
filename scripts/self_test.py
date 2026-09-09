#!/usr/bin/env python3
"""wechat-mp-rss 安装前自检：离线、无副作用。

校验捆绑源码包完整性（解压到临时目录，不写任何持久位置），
并探测本机运行时（Python/Docker/端口），为选择部署路径提供依据。
退出码：0=捆绑源码与离线轮子完整；1=有缺失或损坏。
运行时探测结果仅供参考，不影响退出码。
"""
import shutil
import socket
import sys
import tarfile
import tempfile
from pathlib import Path

try:  # Windows GBK 控制台兜底
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_ROOT = Path(__file__).resolve().parent.parent
TARBALL = SKILL_ROOT / "assets" / "wechat-download-api-src.tar.gz"
KEY_FILES = [
    "wechat-download-api/app.py",
    "wechat-download-api/requirements.txt",
    "wechat-download-api/env.example",
    "wechat-download-api/docker-compose.yml",
    "wechat-download-api/start.sh",
    "wechat-download-api/start.bat",
    "wechat-download-api/LICENSE",
    "wechat-download-api/README.md",
    "wechat-download-api/routes/rss.py",
    "wechat-download-api/routes/export.py",
    "wechat-download-api/static/rss.html",
    "wechat-download-api/utils/epub_render.py",
    "wechat-download-api/tests/test_export.py",
    "wechat-download-api/tests/test_login.py",
    "wechat-download-api/utils/auth_manager.py",
    "wechat-download-api/utils/weread_client.py",
]
FORBIDDEN_SUFFIXES = (".env", ".db")
FORBIDDEN_NAMES = (".credentials.json", ".weread_credentials.json")


def check_bundle() -> bool:
    print(f"[1/4] 捆绑源码包: {TARBALL}")
    if not TARBALL.is_file():
        print("  FAIL 附件缺失")
        return False
    try:
        with tarfile.open(TARBALL, "r:gz") as tf:
            members = tf.getmembers()
            names = {m.name for m in members}
            for m in members:  # 路径安全
                if m.name.startswith(("/", "..")) or ".." in m.name.split("/"):
                    print(f"  FAIL 不安全路径: {m.name}")
                    return False
            missing = [k for k in KEY_FILES if k not in names]
            if missing:
                print(f"  FAIL 关键文件缺失: {missing}")
                return False
            leaked = [n for n in names if n.endswith(FORBIDDEN_SUFFIXES)
                      or n.rsplit("/", 1)[-1] in FORBIDDEN_NAMES
                      or "/static/qrcodes/" in n]
            if leaked:
                print(f"  FAIL 包内出现不应存在的敏感/数据文件: {leaked}")
                return False
            with tempfile.TemporaryDirectory() as td:  # 真实解压验证
                if sys.version_info >= (3, 12):
                    tf.extractall(td, filter="data")
                else:
                    tf.extractall(td)
                if not (Path(td) / "wechat-download-api" / "app.py").is_file():
                    print("  FAIL 解压后结构异常")
                    return False
                source_root = Path(td) / "wechat-download-api"
                core_files = [
                    source_root / "utils" / "rss_poller.py",
                    source_root / "routes" / "articles.py",
                    source_root / "routes" / "admin.py",
                    source_root / "routes" / "search.py",
                ]
                core_text = "\n".join(p.read_text(encoding="utf-8") for p in core_files)
                if "appmsgpublish" in core_text:
                    print("  FAIL 核心抓取链路仍引用已失效的 appmsgpublish")
                    return False
                weread_text = (source_root / "utils" / "weread_client.py").read_text(encoding="utf-8")
                if "/web/mp/articles" not in weread_text:
                    print("  FAIL 微信读书文章列表客户端缺失")
                    return False
                if "/web/login/renewal" not in weread_text or "x-wrpa-0" not in weread_text:
                    print("  FAIL 微信读书 WPA 自动续期或兼容逻辑缺失")
                    return False
            print(f"  OK 共 {len(names)} 个条目，关键文件齐全，无敏感文件，可正常解压")
            return True
    except Exception as e:
        print(f"  FAIL 包损坏或不可读: {e}")
        return False


def probe_runtime() -> None:
    print("[2/4] 运行时探测（仅供部署路径决策）")
    v = sys.version_info
    py_ok = (v.major, v.minor) >= (3, 10)
    print(f"  Python {v.major}.{v.minor}.{v.micro}: {'满足 >=3.10，可走原生路径 B' if py_ok else '过旧，原生路径需先装 Python 3.10+'}")
    docker = shutil.which("docker")
    print(f"  Docker: {'已安装(' + docker + ')，可走路径 A' if docker else '未安装，建议走原生路径 B'}")


def check_wheels() -> bool:
    """离线轮子完整性：目录、数量、关键二进制哨兵。无 wheels 目录视为在线安装版，不算失败。"""
    print("[3/4] 离线依赖轮子")
    wd = SKILL_ROOT / "assets" / "wheels"
    if not wd.is_dir():
        print("  未捆绑离线轮子（在线安装版），跳过")
        return True
    ok = True
    n_any = len(list((wd / "any").glob("*.whl")))
    print(f"  any/（全平台共享纯 Python）: {n_any} 个{'' if n_any >= 40 else '  FAIL 数量异常'}")
    ok &= n_any >= 40
    sentinels = ("curl_cffi", "pydantic_core", "pillow")
    for plat in ("win_amd64-cp312", "macosx_arm64-cp312", "macosx_x86_64-cp312"):
        files = [f.name.lower() for f in (wd / plat).glob("*.whl")]
        missing = [s for s in sentinels if not any(f.startswith(s) for f in files)]
        good = len(files) >= 10 and not missing
        print(f"  {plat}: {len(files)} 个{'' if good else f'  FAIL 缺哨兵 {missing}' }")
        ok &= good
    return ok


def probe_ports() -> None:
    print("[4/4] 端口探测")
    for port in (5000, 5001):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            busy = s.connect_ex(("127.0.0.1", port)) == 0
        print(f"  127.0.0.1:{port} {'已被占用（部署时避开或确认就是本服务）' if busy else '空闲'}")


if __name__ == "__main__":
    ok = check_bundle()
    probe_runtime()
    ok = check_wheels() and ok
    probe_ports()
    print("自检结果:", "PASS（可以开始部署，详见 references/DEPLOY.md）" if ok else "FAIL（附件不完整，向发送方重新索取）")
    sys.exit(0 if ok else 1)
