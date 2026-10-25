# -*- coding: utf-8 -*-
"""Boot launcher: dependency check + install + launch main.py.

Replaces the fragile Chinese echo lines in the .bat (cmd.exe mis-parses
UTF-8 Chinese on GBK consoles even with chcp 65001). Python handles
Unicode reliably, so all user-facing messages live here.
"""
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(BASE_DIR, "requirements.txt")
MAIN_PY = os.path.join(BASE_DIR, "main.py")
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def run_silent(*args):
    try:
        r = subprocess.run([sys.executable] + list(args),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           cwd=BASE_DIR)
        return r.returncode == 0
    except Exception:
        return False


def pip_install(mirror=None):
    cmd = [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS]
    if mirror:
        cmd += ["-i", mirror]
    return subprocess.run(cmd, cwd=BASE_DIR).returncode == 0


def deps_ok():
    return run_silent("-c", "import flask, requests, wechatauto")


def main(argv):
    check_only = "--check" in argv[1:]
    print("=" * 58)
    print("      微信小号情感陪伴聊天机器人 · 一键启动")
    print("=" * 58)
    print()
    print("[1/3] Python 解释器: %s" % sys.executable)
    print("[2/3] 正在检查依赖库...")
    if not deps_ok():
        print("      首次运行或缺少依赖，正在自动安装，请耐心等待 1-3 分钟...")
        if not os.path.exists(REQUIREMENTS):
            print("[错误] 找不到 requirements.txt，无法自动安装依赖。")
            input("按回车退出...")
            return 1
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=BASE_DIR)
        if not pip_install():
            print("      默认源安装失败，正在改用国内镜像重试...")
            if not pip_install(mirror=MIRROR):
                print()
                print("[错误] 依赖自动安装失败，请检查网络后重新双击启动，")
                print("       或手动执行: %s -m pip install -r requirements.txt"
                      % sys.executable)
                print()
                input("按回车退出...")
                return 1
        print("      依赖安装完成。")
    print("      依赖已就绪。")
    if check_only:
        print()
        print("[自检通过] Python 与依赖均正常，双击启动文件即可启动机器人。")
        return 0

    print()
    print("[3/3] 正在启动控制台...")
    print()
    print("  打开后是「未启动」状态，先在网页里把这两样设好：")
    print("    1) 挑一个人设（🎭 人设）——决定它用什么性格跟你聊天")
    print("    2) 填大模型 API Key（🧠 AI 大脑）——决定它靠什么思考和回复")
    print("  弄好之后，点网页上的「🚀 启动」，它才会连微信并开始自动回消息。")
    print("  网页控制台: http://127.0.0.1:5000   （服务器就绪后自动打开，只开一次）")
    print("  关闭本窗口或按 Ctrl+C 即退出。")
    print()
    print("-" * 58)
    print("  提示: 不点网页上的「🚀 启动」，它就不会连微信、也不会回任何人。")
    print("-" * 58)
    print()
    # 注意：这里刻意不传 --start。
    # 传了 --start 会让 main.py 无视 auto_start=False 配置，强制连微信开始自动回复，
    # 新手就来不及先设人设和 API Key 了。默认必须是「未启动」状态。
    args = [sys.executable, MAIN_PY]
    if "--start" in argv[1:]:
        args.append("--start")
        print("[可选] 检测到 --start：本次将直接连微信并进入全自动运行模式。")
        print()
    rc = subprocess.run(args, cwd=BASE_DIR).returncode
    if rc != 0:
        print()
        print("[提示] 程序已退出，返回码 %s。" % rc)
        print("       若上方出现报错信息，请截图反馈；常见原因：")
        print("       1. 机器人已经在运行（请直接访问 http://127.0.0.1:5000，不要重复启动）")
        print("       2. 电脑微信未登录或未在后台运行")
        print("       3. 端口 5000 被其他程序占用（可在 config.py 里改 WEB_UI_PORT）")
        print()
        input("按回车退出...")
        return rc
    print()
    print("机器人已退出，自动回复已停止。")
    input("按回车退出...")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
