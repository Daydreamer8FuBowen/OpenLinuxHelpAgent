#!/usr/bin/env python3
import argparse
from LinuxAgent import __version__

def parse_args():
    parser = argparse.ArgumentParser(description="命令行工具示例")

    parser.add_argument(
        "text",
        nargs=argparse.REMAINDER,
        help="要处理的文本",
        default=None
    )

    parser.add_argument(
        "-p",
        nargs="?",
        type=int,
        help="查看之前的命令条数（默认10）",
        default=None,
        const=10
    )

    parser.add_argument(
        "-y",
        action="store_true",
        help="运行执行白名单指令"
    )

    parser.add_argument(
        "-v",
        action="store_true",
        help="查看版本信息（简略）"
    )

    parser.add_argument(
        "-V",
        action="store_true",
        help="查看版本信息（详细）"
    )

    parser.add_argument(
        "--token",
        action="store_true",
        help="查看 token 消耗情况"
    )

    parser.add_argument(
        "-c",
        action="store_true",
        help="查看系统配置文件"
    )

    return parser.parse_args()


def main():
    args = parse_args()

if __name__ == "__main__":
    main()
