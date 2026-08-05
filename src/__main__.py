import sys

from src.main import main


if __name__ == "__main__":
    args = list(sys.argv[1:])
    # 打包产物（PyInstaller frozen）默认以编辑器（新客户端）模式启动，
    # 但保留外部参数（如 --smoke-test）
    if getattr(sys, "frozen", False) and "--editor" not in args:
        args.append("--editor")
    raise SystemExit(main(args or None))
