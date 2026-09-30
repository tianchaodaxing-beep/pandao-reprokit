"""无 shell 执行、有限等待、输出匹配与超时进程清理。"""
import codecs
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from .adapter import TaskError


def scan_output(path, marker, encoding):
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    matched, carry, tail = False, "", ""
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(65536)
            value = decoder.decode(chunk, final=not chunk)
            combined = carry + value
            matched = matched or marker in combined
            carry = combined[-max(1, len(marker)):]
            tail = (tail + value)[-4000:]
            if not chunk:
                return matched, tail


def run_command(argv, *, cwd, timeout, marker, encoding="utf-8"):
    started = time.monotonic()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    with tempfile.TemporaryDirectory(prefix="pandao-repro-log-") as directory:
        stdout, stderr = Path(directory) / "stdout", Path(directory) / "stderr"
        timed_out = False
        with stdout.open("wb") as out, stderr.open("wb") as err:
            try:
                process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                           stdout=out, stderr=err, shell=False,
                                           start_new_session=(os.name != "nt"))
            except OSError as error:
                raise TaskError(f"命令无法启动：{error}") from error
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    cleanup = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                             capture_output=True, timeout=10)
                    if cleanup.returncode and process.poll() is None:
                        process.kill()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.wait(timeout=10)
        out_match, out_tail = scan_output(stdout, marker, encoding)
        err_match, err_tail = scan_output(stderr, marker, encoding)
    return {"exit_code": process.returncode, "timed_out": timed_out,
            "matched": out_match or err_match, "seconds": round(time.monotonic() - started, 4),
            "stdout_tail": out_tail, "stderr_tail": err_tail}
