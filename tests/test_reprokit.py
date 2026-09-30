import csv
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from pandao_repro.adapter import Adapter, TaskError
from pandao_repro.cli import main, verify
from pandao_repro.core import Settings, UnstableError, reduce_file
from pandao_repro.process import run_command, scan_output


def job(tmp_path, raw, script, **kwargs):
    source = tmp_path / "原始 中文输入.txt"
    source.write_bytes(raw)
    validator = tmp_path / "validator.py"
    validator.write_text(script, encoding="utf-8")
    return Settings(source=source, out=tmp_path / "结果", command=[sys.executable, str(validator), "{input}"],
                    match="E_TARGET", cwd=tmp_path, **kwargs)


TEXT_CHECK = 'from pathlib import Path\nimport sys\ns=Path(sys.argv[1]).read_text(encoding="utf-8")\nif "BAD" in s:\n print("E_TARGET", file=sys.stderr)\n sys.exit(7)\n'


def test_text_reduce_real_process_and_replay(tmp_path):
    settings = job(tmp_path, b"normal\nBAD\nother\n", TEXT_CHECK)
    original = settings.source.read_bytes()
    result = reduce_file(settings)
    assert result["kept_positions"] == [2]
    assert result["one_minimal"] and result["independent_verified"]
    assert settings.source.read_bytes() == original
    assert (settings.out / "缩减样本" / settings.source.name).read_bytes() == b"BAD\n"
    assert verify(settings.out / "复现配置.json") == 0


def test_csv_header_multiline_quote_and_two_record_combination(tmp_path):
    script = 'import csv,sys\nr=list(csv.DictReader(open(sys.argv[1], encoding="utf-8", newline="")))\ns={x["规则"] for x in r}\nif {"甲\\n规则", "乙规则"} <= s:\n print("E_TARGET")\n sys.exit(9)\n'
    raw = '编号,规则\n1,正常\n2,"甲\n规则"\n3,乙规则\n4,其他\n'.encode()
    settings = job(tmp_path, raw, script, kind="csv")
    result = reduce_file(settings)
    assert result["kept_positions"] == [2, 3]
    text = (settings.out / "缩减样本" / settings.source.name).read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows == [["编号", "规则"], ["2", "甲\n规则"], ["3", "乙规则"]]
    assert result["one_minimal"] and result["independent_verified"]


def test_nested_json_keeps_outer_structure(tmp_path):
    document = {"meta": {"required": True}, "wrapper": [{"items": [{"rule": "ok"}, {"rule": "BAD"}, {"rule": "other"}]}], "extra": [1, 2]}
    script = 'import json,sys\nd=json.load(open(sys.argv[1], encoding="utf-8"))\nassert d["meta"]["required"] and d["extra"]==[1,2]\nif any(x["rule"]=="BAD" for x in d["wrapper"][0]["items"]):\n print("E_TARGET")\n sys.exit(3)\n'
    settings = job(tmp_path, json.dumps(document).encode(), script, kind="json", pointer="/wrapper/0/items")
    result = reduce_file(settings)
    reduced = json.loads((settings.out / "缩减样本" / settings.source.name).read_bytes())
    assert reduced["wrapper"][0]["items"] == [{"rule": "BAD"}]
    assert reduced["meta"] == document["meta"] and reduced["extra"] == [1, 2]
    assert result["one_minimal"]


def test_root_json_and_pointer_escaping():
    adapter = Adapter(b'{"a/b":{"~x":[1,2]},"fixed":true}', kind="json", pointer="/a~1b/~0x")
    assert json.loads(adapter.build([1])) == {"a/b": {"~x": [2]}, "fixed": True}
    assert json.loads(Adapter(b"[1,2,3]", kind="json").build([2])) == [3]


@pytest.mark.parametrize("raw,pointer", [(b'{"x":1,"x":2}', ""), (b'[NaN]', ""), (b'{"x":1}', "/x"), (b'{"x":[]}', "/missing"), (b'{"x":[]}', "/x~3")])
def test_invalid_json_rejected(raw, pointer):
    with pytest.raises(TaskError):
        Adapter(raw, kind="json", pointer=pointer)


def test_csv_bom_and_semicolon_preserved():
    adapter = Adapter(b'\xef\xbb\xbfid;rule\r\n1;BAD\r\n2;ok\r\n', kind="csv", delimiter=";")
    assert adapter.build([0]) == b'\xef\xbb\xbfid;rule\r\n1;BAD\r\n'


def test_uninteresting_initial_input_is_readable_error(tmp_path):
    settings = job(tmp_path, b"healthy\n", TEXT_CHECK)
    with pytest.raises(TaskError, match="没有触发指定错误"):
        reduce_file(settings)
    assert json.loads((settings.out / "失败结论.json").read_bytes())["independent_verified"] is False


def test_wrong_exit_code_is_not_target(tmp_path):
    settings = job(tmp_path, b"BAD\n", TEXT_CHECK, expected_exit=88)
    with pytest.raises(TaskError, match="没有触发指定错误"):
        reduce_file(settings)


def test_budget_stops_and_preserves_verified_sample(tmp_path):
    settings = job(tmp_path, b"a\nb\nBAD\nc\nd\ne\nf\n", TEXT_CHECK, max_tests=12)
    result = reduce_file(settings)
    assert result["executions"] <= 12
    assert result["status"] == "limited" and result["independent_verified"]
    assert not result["one_minimal"]


def test_empty_failing_input_is_supported(tmp_path):
    script = 'import sys\nprint("E_TARGET")\nsys.exit(7)\n'
    settings = job(tmp_path, b"a\nb\n", script)
    result = reduce_file(settings)
    assert result["output_units"] == 0 and result["one_minimal"]


def test_nondeterministic_initial_error_is_rejected(tmp_path):
    script = 'from pathlib import Path\nimport sys\np=Path("counter")\nn=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\nif n%2:\n print("E_TARGET")\n sys.exit(7)\n'
    settings = job(tmp_path, b"BAD\n", script)
    with pytest.raises(UnstableError):
        reduce_file(settings)
    assert (settings.out / "失败结论.md").is_file()


def test_mutating_command_is_rejected_without_touching_source(tmp_path):
    script = 'from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text("changed")\nprint("E_TARGET")\nsys.exit(7)\n'
    settings = job(tmp_path, b"original\n", script)
    with pytest.raises(TaskError, match="修改了输入副本"):
        reduce_file(settings)
    assert settings.source.read_bytes() == b"original\n"


def test_existing_out_is_never_overwritten(tmp_path):
    settings = job(tmp_path, b"BAD\n", TEXT_CHECK)
    settings.out.mkdir()
    marker = settings.out / "keep"
    marker.write_text("keep")
    with pytest.raises(TaskError, match="已存在"):
        reduce_file(settings)
    assert marker.read_text() == "keep"


def test_rebuilt_csv_must_reproduce_original_error(tmp_path):
    script = 'from pathlib import Path\nimport sys\ns=Path(sys.argv[1]).read_bytes()\nif not s.endswith(b"\\n"):\n print("E_TARGET")\n sys.exit(7)\n'
    settings = job(tmp_path, b"id,rule\n1,BAD", script, kind="csv")
    with pytest.raises(TaskError, match="重建后"):
        reduce_file(settings)


def test_artifact_name_does_not_collide_with_report(tmp_path):
    settings = job(tmp_path, b"BAD\n", TEXT_CHECK)
    new_source = tmp_path / "结论.json"
    settings.source.rename(new_source)
    settings.source = new_source
    result = reduce_file(settings)
    assert json.loads((settings.out / "结论.json").read_bytes()) == result
    assert (settings.out / "缩减样本" / "结论.json").read_bytes() == b"BAD\n"


def test_marker_found_across_large_output_chunks(tmp_path):
    target = tmp_path / "log"
    target.write_bytes(b"x" * 65534 + b"E_TARGET" + b"y" * 70000)
    matched, tail = scan_output(target, "E_TARGET", "utf-8")
    assert matched and len(tail) <= 4000


def test_timeout_is_not_success(tmp_path):
    result = run_command([sys.executable, "-c", 'import time; print("E_TARGET", flush=True); time.sleep(5)'],
                         cwd=tmp_path, timeout=0.15, marker="E_TARGET")
    assert result["timed_out"]


def test_command_arguments_are_not_shell_expanded(tmp_path):
    marker = tmp_path / "should-not-exist"
    result = run_command([sys.executable, "-c", "import sys; print(sys.argv[1])", f"; touch {marker}"],
                         cwd=tmp_path, timeout=3, marker="touch")
    assert result["matched"] and result["exit_code"] == 0 and not marker.exists()


def test_verify_refuses_tampered_sample(tmp_path):
    settings = job(tmp_path, b"BAD\n", TEXT_CHECK)
    reduce_file(settings)
    (settings.out / "缩减样本" / settings.source.name).write_bytes(b"different")
    with pytest.raises(TaskError, match="修改"):
        verify(settings.out / "复现配置.json")


@pytest.mark.parametrize("changes", [{"timeout": 0}, {"seconds": float("inf")}, {"max_tests": 1}, {"confirm": 1}, {"command": ["python"]}])
def test_invalid_limits_and_command_rejected(tmp_path, changes):
    settings = job(tmp_path, b"BAD\n", TEXT_CHECK)
    for key, value in changes.items():
        setattr(settings, key, value)
    with pytest.raises(TaskError):
        settings.validate()


def test_cli_gives_nonzero_when_initial_input_is_healthy(tmp_path, capsys):
    settings = job(tmp_path, b"healthy\n", TEXT_CHECK)
    code = main(["reduce", "--input", str(settings.source), "--out", str(settings.out), "--match", "E_TARGET", "--", *settings.command])
    assert code == 2 and "无法完成" in capsys.readouterr().err


def test_cli_in_separate_process(tmp_path):
    settings = job(tmp_path, b"ok\nBAD\n", TEXT_CHECK)
    result = subprocess.run([sys.executable, "-m", "pandao_repro", "reduce", "--input", str(settings.source), "--out", str(settings.out), "--match", "E_TARGET", "--", *settings.command],
                            capture_output=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert "三次通过" in result.stdout


def test_insufficient_budget_for_high_confirmation_is_rejected(tmp_path):
    settings = job(tmp_path, b"BAD\n", TEXT_CHECK, max_tests=12, confirm=5)
    with pytest.raises(TaskError, match="预留"):
        settings.validate()


def test_early_time_limit_is_reported_without_assertion(tmp_path):
    settings = job(tmp_path, b"BAD\n", TEXT_CHECK, seconds=0.000001)
    code = main(["reduce", "--input", str(settings.source), "--out", str(settings.out), "--match", "E_TARGET", "--seconds", "0.000001", "--", *settings.command])
    assert code == 2
    assert (settings.out / "失败结论.md").is_file()


def test_source_change_is_not_reported_as_success(tmp_path):
    settings = job(tmp_path, b"ok\nBAD\n", TEXT_CHECK)
    original = settings.source.read_bytes()
    validator = Path(settings.command[1])
    validator.write_text('from pathlib import Path\nPath(' + repr(str(settings.source)) + ').write_text("external change")\n' + TEXT_CHECK, encoding="utf-8")
    result = reduce_file(settings)
    assert result["status"] == "source_changed" and not result["source_unchanged"]
    assert not result["independent_verified"] and not result["one_minimal"]
    assert (settings.out / "原始输入副本" / settings.source.name).read_bytes() == original


def test_verify_refuses_outside_sample_path(tmp_path):
    config = {"command": [sys.executable, "{input}"], "input": "../outside.txt", "cwd": str(tmp_path),
              "match": "E_TARGET", "exit_code": 7, "timeout": 1, "output_encoding": "utf-8", "sha256": "x"}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(TaskError, match="结果目录内"):
        verify(path)
