"""中文命令入口；命令参数以独立列表传入，不经过 shell。"""
import argparse
from .i18n import Parser, configure, t, write_summary
import datetime
import hashlib
import json
import math
from pathlib import Path
import sys

from .adapter import TaskError
from .core import BudgetExceeded, Settings, reduce_file
from .process import run_command


def verify(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {"command", "input", "cwd", "match", "exit_code", "timeout", "output_encoding", "sha256"}
    if not isinstance(config, dict) or not required.issubset(config):
        raise TaskError("复现配置缺少必要内容")
    if (not isinstance(config["command"], list) or not config["command"]
            or not all(isinstance(p, str) for p in config["command"])
            or not any("{input}" in p for p in config["command"])
            or not isinstance(config["match"], str) or not config["match"]
            or not isinstance(config["exit_code"], int)
            or not isinstance(config["timeout"], (int, float)) or not math.isfinite(config["timeout"]) or config["timeout"] <= 0
            or not all(isinstance(config[key], str) for key in ["input", "cwd", "output_encoding", "sha256"])):
        raise TaskError("复现配置的命令或判定内容无效")
    sample = (path.parent / config["input"]).resolve()
    if not sample.is_relative_to(path.parent):
        raise TaskError("复现样本路径必须位于结果目录内")
    if hashlib.sha256(sample.read_bytes()).hexdigest() != config["sha256"]:
        raise TaskError("样本已被修改，与保存的复现记录不一致")
    argv = [part.replace("{input}", str(sample)).replace("{python}", sys.executable)
            for part in config["command"]]
    results, unchanged = [], True
    for _ in range(3):
        results.append(run_command(argv, cwd=config["cwd"], timeout=config["timeout"],
                                   marker=config["match"], encoding=config["output_encoding"]))
        if not sample.exists() or hashlib.sha256(sample.read_bytes()).hexdigest() != config["sha256"]:
            unchanged = False
            break
    passed = unchanged and all(not r["timed_out"] and r["matched"] and r["exit_code"] == config["exit_code"] for r in results)
    (path.parent / "再次复现结果.json").write_text(
        json.dumps({"passed": passed, "sample_unchanged": unchanged, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("同一错误连续三次复现通过。" if passed else "复现核对未通过，请检查程序环境与错误原文。")
    return 0 if passed else 4


def main(argv=None):
    argv = configure(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = Parser(description="将出错文件缩减为仍能复现同一错误的小样本")
    parser.add_argument("--lang", choices=["zh", "en"], default="zh", help="Display language: zh or en")
    subs = parser.add_subparsers(dest="action", required=True)
    run = subs.add_parser("reduce", help="缩减出错输入")
    run.add_argument("--input", required=True, type=Path, help="原输入文件")
    run.add_argument("--out", required=True, type=Path, help="新的输出目录")
    run.add_argument("--format", choices=["lines", "csv", "json"], default="lines", help="输入格式")
    run.add_argument("--json-pointer", default="", help="JSON 内的记录数组，例如 /items")
    run.add_argument("--delimiter", default=",", help="CSV 分隔符")
    run.add_argument("--encoding", default="utf-8", help="输入文件编码")
    run.add_argument("--output-encoding", default="utf-8", help="程序输出编码")
    run.add_argument("--match", required=True, help="能够区分目标错误的原文，按字面匹配")
    run.add_argument("--exit-code", type=int, help="目标退出码；省略时从原始失败中读取")
    run.add_argument("--cwd", type=Path, default=Path.cwd(), help="原命令的工作目录")
    run.add_argument("--timeout", type=float, default=10, help="每次命令最多运行的秒数")
    run.add_argument("--seconds", type=float, default=300, help="整个任务的用时上限")
    run.add_argument("--max-tests", type=int, default=300, help="命令执行次数上限，包含核对")
    run.add_argument("--confirm", type=int, default=2, help="候选样本重复运行次数，2 至 5")
    run.add_argument("command", nargs=argparse.REMAINDER, help="-- 后跟原命令，用 {input} 代表输入副本")
    check = subs.add_parser("verify", help="再次独立复现保存的样本")
    check.add_argument("config", type=Path)
    demo = subs.add_parser("demo", help="运行明确标注的模拟故障示例")
    demo.add_argument("--out", type=Path, default=None, help="新的演示目录")
    args = parser.parse_args(argv)
    try:
        if args.action == "verify":
            return verify(args.config)
        if args.action == "demo":
            from .demo import make_demo
            output = args.out or Path.cwd() / "演示结果" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            source = make_demo(output)
            print(t("正在运行模拟故障示例；不代表真实业务数据。"), flush=True)
            report = reduce_file(Settings(source=source, out=output / "缩减结果", kind="csv",
                                          match="E_RULE_COLLISION", command=["{python}", "-m", "pandao_repro.demo", "{input}"]))
            destination = output / "缩减结果"
        else:
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            report = reduce_file(Settings(source=args.input, out=args.out, command=command, match=args.match,
                                          kind=args.format, pointer=args.json_pointer, encoding=args.encoding,
                                          output_encoding=args.output_encoding, delimiter=args.delimiter, cwd=args.cwd,
                                          expected_exit=args.exit_code, timeout=args.timeout, seconds=args.seconds,
                                          max_tests=args.max_tests, confirm=args.confirm))
            destination = args.out
        print(t(f"保留 {report['output_units']} / {report['input_units']} 项；执行 {report['executions']} 次。"))
        print(t("最终样本独立复现：" + ("三次通过" if report["independent_verified"] else "未通过")))
        print(t("逐项删除核对：" + ("通过" if report["one_minimal"] else "未完成")))
        print(t("结果目录：" + str(destination.resolve())))
        return 0 if report["status"] == "completed" and report["one_minimal"] else (3 if report["independent_verified"] else 4)
    except (TaskError, BudgetExceeded, OSError, json.JSONDecodeError) as error:
        print(t("无法完成：" + str(error)), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
