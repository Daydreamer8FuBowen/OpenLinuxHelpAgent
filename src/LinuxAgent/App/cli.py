from __future__ import annotations
"""
应用层 CLI
职责：
- 定义命令行参数并提供统一解析入口
"""

import argparse


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="命令行工具示例", add_help=False)
    parser.add_argument("--help", action="help", help="查看帮助信息并退出")
    parser.add_argument("text", nargs=argparse.REMAINDER, help="要处理的文本", default=None)
    parser.add_argument("-h", nargs="?", type=int, help="查看历史对话轮数（默认5）", default=None, const=5)
    parser.add_argument("-p", nargs="?", type=int, help="查看之前的命令条数（默认10）", default=None, const=10)
    parser.add_argument("-y", action="store_true", help="运行执行白名单指令", default=True)
    parser.add_argument("--test", action="store_true", help="在 Docker 测试环境中执行白名单指令")
    parser.add_argument("-v", action="store_true", help="查看版本信息（简略）")
    parser.add_argument("-V", action="store_true", help="查看版本信息（详细）")
    parser.add_argument("--token", action="store_true", help="查看 token 消耗情况")
    parser.add_argument("-c", action="store_true", help="查看系统配置文件")
    return parser


def parse_args():
    """解析命令行参数并返回 Namespace。"""
    return build_parser().parse_args()
