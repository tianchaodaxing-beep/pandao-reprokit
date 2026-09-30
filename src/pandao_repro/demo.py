"""模拟两条记录的组合触发规则冲突；演示数据不来自业务。"""
import csv
from pathlib import Path
import sys


def make_demo(directory):
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / "模拟导入.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["编号", "规则"])
        for index in range(256):
            writer.writerow([str(index + 1), "甲规则" if index == 43 else "乙规则" if index == 187 else "普通记录"])
    return source


def check(path):
    with open(path, encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rules = {row["规则"] for row in rows}
    if "甲规则" in rules and "乙规则" in rules:
        print("E_RULE_COLLISION：甲规则与乙规则同时出现，模拟导入失败。", file=sys.stderr)
        return 7
    print("模拟导入成功。")
    return 0


if __name__ == "__main__":
    raise SystemExit(check(sys.argv[1]))
