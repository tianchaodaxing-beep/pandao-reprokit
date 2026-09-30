"""调用原版 Picire 引擎，独立核对缩减样本及逐项删除结果。"""
from dataclasses import dataclass, field
import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from picire import DD, Outcome, ReductionError, ReductionStopped

from . import __version__
from .adapter import Adapter, TaskError
from .process import run_command


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class BudgetExceeded(ReductionStopped):
    pass


class UnstableError(TaskError):
    pass


@dataclass
class Settings:
    source: Path
    out: Path
    command: list[str]
    match: str
    kind: str = "lines"
    pointer: str = ""
    encoding: str = "utf-8"
    output_encoding: str = "utf-8"
    delimiter: str = ","
    cwd: Path = field(default_factory=Path.cwd)
    expected_exit: int | None = None
    timeout: float = 10
    max_tests: int = 300
    seconds: float = 300
    confirm: int = 2

    def validate(self):
        self.source, self.out, self.cwd = self.source.resolve(), self.out.resolve(), self.cwd.resolve()
        if not self.source.is_file() or not self.cwd.is_dir():
            raise TaskError("输入文件或命令工作目录不存在")
        if not self.command or not any("{input}" in part for part in self.command):
            raise TaskError("命令必须包含 {input}，它会替换为输入副本路径")
        if not self.match:
            raise TaskError("--match 不能为空，请填写能够区分目标错误的原文")
        if not all(math.isfinite(value) and value > 0 for value in [self.timeout, self.seconds]):
            raise TaskError("时间限制必须为有限正数")
        if not 2 <= self.confirm <= 5 or self.max_tests < max(12, 2 * self.confirm + 4):
            raise TaskError("--confirm 应为 2 至 5；--max-tests 至少为 12，且须预留原始核对及最终三次复现的次数")
        if self.source.stat().st_size > 32 * 1024 * 1024:
            raise TaskError("首版支持不超过 32 MiB 的输入文件")
        try:
            "".encode(self.encoding)
            "".encode(self.output_encoding)
        except LookupError as error:
            raise TaskError("指定的编码不存在") from error
        if self.out.exists():
            raise TaskError("输出目录已存在，请指定一个新目录，原有结果不会被覆盖")


class Probe:
    def __init__(self, settings, adapter):
        self.settings, self.adapter = settings, adapter
        self.started = time.monotonic()
        self.count, self.timeouts = 0, 0
        self.expected = settings.expected_exit
        self.best = list(range(len(adapter.units)))
        self.known = {}
        self.last = None
        self.cases = settings.out / "尝试"
        self.cases.mkdir()

    def trial(self, raw, *, reserve=3, actual=None, phase="缩减"):
        remaining = self.settings.seconds - (time.monotonic() - self.started)
        if self.count >= self.settings.max_tests - reserve:
            raise BudgetExceeded("达到命令执行次数限制")
        if remaining <= 0:
            raise BudgetExceeded("达到总用时限制")
        self.count += 1
        path = actual or self.cases / self.settings.source.name
        if actual is None:
            path.write_bytes(raw)
        if digest(path.read_bytes()) != digest(raw):
            raise TaskError("待执行样本与记录不一致")
        argv = [part.replace("{input}", str(path)).replace("{python}", sys.executable)
                for part in self.settings.command]
        result = run_command(argv, cwd=self.settings.cwd,
                             timeout=min(self.settings.timeout, remaining), marker=self.settings.match,
                             encoding=self.settings.output_encoding)
        if not path.exists() or digest(path.read_bytes()) != digest(raw):
            raise TaskError("命令修改了输入副本，请改用不修改输入文件的复现命令")
        if result["timed_out"]:
            self.timeouts += 1
            outcome = "unknown"
        elif result["matched"] and (self.expected is None or result["exit_code"] == self.expected):
            outcome = "fail"
        else:
            outcome = "pass"
        self.last = result
        with (self.settings.out / "尝试记录.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"number": self.count, "phase": phase, "outcome": outcome,
                                     "input_sha256": digest(raw), **result}, ensure_ascii=False) + "\n")
        return outcome

    def stable(self, raw, *, phase="缩减"):
        outcomes = [self.trial(raw, phase=phase) for _ in range(self.settings.confirm)]
        if "unknown" in outcomes:
            return "unknown"
        if len(set(outcomes)) != 1:
            raise UnstableError("相同样本出现不同结果，目标错误不能稳定复现")
        key = digest(raw)
        previous = self.known.get(key)
        if previous is not None and previous != outcomes[0]:
            raise UnstableError("同一份样本在前后执行中出现不同结果")
        self.known[key] = outcomes[0]
        return outcomes[0]

    def __call__(self, indexes, content, config_id):
        outcome = self.stable(content)
        if outcome == "fail" and len(indexes) < len(self.best):
            self.best = list(indexes)
        return Outcome.FAIL if outcome == "fail" else Outcome.PASS


def _report(settings, probe, adapter, original, *, status, reason, minimal, verified, kept):
    target = settings.out / "缩减样本" / settings.source.name
    content = target.read_bytes() if target.exists() else b""
    source_unchanged = settings.source.is_file() and digest(settings.source.read_bytes()) == digest(original)
    if not source_unchanged:
        status, reason, verified, minimal = "source_changed", "原文件在运行期间发生变化，请检查后重新运行", False, False
    report = {"version": __version__, "status": status, "reason": reason,
              "format": settings.kind, "json_pointer": settings.pointer,
              "input_units": len(adapter.units), "output_units": len(kept),
              "kept_positions": [i + 1 for i in kept], "executions": probe.count,
              "timeout_executions": probe.timeouts, "independent_verified": verified,
              "one_minimal": minimal, "source_unchanged": source_unchanged,
              "source_sha256": digest(original), "output_sha256": digest(content),
              "seconds": round(time.monotonic() - probe.started, 3),
              "created_at": datetime.datetime.now().astimezone().isoformat()}
    (settings.out / "结论.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    titles = {"completed": "缩减完成", "limited": "达到限制，已保存当前样本", "unstable": "错误不能稳定复现",
              "unverified": "独立复现核对未通过", "source_changed": "原文件发生变化"}
    lines = ["# " + titles.get(status, status), "", reason, "",
             f"原输入：{len(adapter.units)} 项。保留：{len(kept)} 项。",
             f"实际执行命令：{probe.count} 次。",
             "原文件内容核对：" + ("未改变" if source_unchanged else "发生变化"),
             "最终样本独立复现：" + ("连续三次通过" if verified else "未完成或未通过"),
             "逐项删除核对：" + ("每项单独删除后都不能稳定触发目标错误" if minimal else "未完成；不能宣称最小样本"),
             "", "保留项的位置：" + (", ".join(str(i + 1) for i in kept) or "无"), "",
             "保留项是仍能触发目标错误的组合，不等于已经查明根因。",
             "", "复现：在相同程序环境中运行 python 复现.py。"]
    (settings.out / "结论.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = {"command": settings.command, "input": "缩减样本/" + settings.source.name, "cwd": str(settings.cwd),
              "match": settings.match, "exit_code": probe.expected, "timeout": settings.timeout,
              "output_encoding": settings.output_encoding, "sha256": digest(content)}
    (settings.out / "复现配置.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    (settings.out / "复现.py").write_text(
        'from pathlib import Path\nfrom pandao_repro.cli import main\n'
        'raise SystemExit(main(["verify", str(Path(__file__).with_name("复现配置.json"))]))\n', encoding="utf-8")
    return report


def reduce_file(settings):
    settings.validate()
    original = settings.source.read_bytes()
    adapter = Adapter(original, kind=settings.kind, encoding=settings.encoding,
                      delimiter=settings.delimiter, pointer=settings.pointer)
    settings.out.mkdir(parents=True)
    (settings.out / "原始输入副本").mkdir()
    (settings.out / "原始输入副本" / settings.source.name).write_bytes(original)
    try:
        return _execute(settings, original, adapter)
    except (TaskError, OSError, BudgetExceeded) as error:
        (settings.out / "失败结论.md").write_text("# 未完成\n\n" + str(error) + "\n\n未生成通过核对的缩减结论。原始输入副本已保存。\n", encoding="utf-8")
        (settings.out / "失败结论.json").write_text(json.dumps({"status": "failed", "reason": str(error), "independent_verified": False}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise


def _execute(settings, original, adapter):
    probe = Probe(settings, adapter)
    # Test the exact original bytes before testing the serializer's output.
    first = probe.trial(original, phase="原始输入")
    if first != "fail":
        raise TaskError("原始输入没有触发指定错误，或执行超时；请检查命令、错误原文和退出码")
    if probe.expected is None:
        if probe.last["exit_code"] == 0:
            raise TaskError("原命令正常退出；如结果确实错误，请明确指定 --exit-code 0")
        probe.expected = probe.last["exit_code"]
    if probe.stable(original, phase="原始输入核对") != "fail":
        raise TaskError("原始输入不能稳定触发指定错误")
    full = list(range(len(adapter.units)))
    if probe.stable(adapter.build(full), phase="结构重建核对") != "fail":
        raise TaskError("文件重建后不再触发同一错误；请改用 --format lines 保留原始文本")
    status, reason, minimal, verified = "completed", "已保留仍能稳定触发目标错误的样本。", False, False
    try:
        if probe.stable(adapter.build([])) == "fail":
            probe.best = []
        else:
            reducer = DD(probe, test_builder=adapter.build)
            reducer(full)
        # Independently cover even the empty deletion of a one-unit result.
        minimal = True
        while True:
            removed = False
            for index in list(probe.best):
                candidate = [i for i in probe.best if i != index]
                outcome = probe.stable(adapter.build(candidate), phase="逐项删除核对")
                if outcome == "unknown":
                    minimal = False
                if outcome == "fail":
                    probe.best = candidate
                    removed = True
                    break
            if not removed:
                break
    except (BudgetExceeded, ReductionStopped) as error:
        status, reason, minimal = "limited", str(error), False
    except ReductionError as error:
        if isinstance(error.__cause__, UnstableError):
            status, reason, minimal = "unstable", str(error.__cause__), False
        elif isinstance(error.__cause__, TaskError):
            raise error.__cause__ from error
        else:
            raise
    except UnstableError as error:
        status, reason, minimal = "unstable", str(error), False
    (settings.out / "缩减样本").mkdir()
    target = settings.out / "缩减样本" / settings.source.name
    payload = adapter.build(probe.best)
    target.write_bytes(payload)
    try:
        results = [probe.trial(payload, reserve=0, actual=target, phase="最终独立核对") for _ in range(3)]
        verified = results == ["fail"] * 3
    except BudgetExceeded:
        verified = False
    if not verified:
        status, reason, minimal = "unverified", "最终样本未能完成三次独立复现核对，请先检查复现环境。", False
    return _report(settings, probe, adapter, original, status=status, reason=reason,
                   minimal=minimal and verified, verified=verified, kept=probe.best)
