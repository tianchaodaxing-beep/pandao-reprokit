# PANDAO 故障缩减工具

基于 [Picire](https://github.com/renatahodovan/picire) 二次开发。将一份出错输入逐步缩成仍能复现同一个错误的小样本，供开发人员和软件服务商排查。

适用于有本机命令入口、能够稳定复现的导入或文本处理错误。首版支持文本行、保留表头的 CSV，以及 JSON 中指定数组内的记录。

## 相比原版新增

- 直接填写原命令、目标错误原文及退出码，无需另写判定脚本。
- 缩减 CSV 时保留表头；缩减 JSON 数组时保留外层对象及其他内容。
- 先核对原始输入，再核对重建后的输入；格式变化使原错误消失时给出明确处理方式。
- 最终样本连续三次独立复现，并检查逐项删除后的结果。
- 保存中文结论、原始副本、保留项位置、尝试记录与再次复现入口。
- 次数和时间均有上限；达到限制时保留当前结果并明确说明核对情况。

原版的缩减算法和模块保留在 `src/picire`，新增流程位于 `src/pandao_repro`。保留原作者版权、许可证及来源说明；本项目不代表原作者背书。

## 安装和试用

需要 Python 3.10 或更新版本。在项目目录运行：

```console
python -m venv .venv
```

Windows：

```console
.venv\Scripts\python -m pip install .
.venv\Scripts\python -m pandao_repro demo
```

Windows 也可双击 `运行故障缩减演示.cmd`。演示会生成明确标注的模拟记录，不使用真实业务数据。

Linux 或 macOS：

```console
.venv/bin/python -m pip install .
.venv/bin/python -m pandao_repro demo
```

## 用自己的命令

例如已有 `importer.py` 读取 CSV，目标错误原文为 `E_RULE_COLLISION`：

```console
python -m pandao_repro reduce --input input.csv --format csv --match E_RULE_COLLISION --out result -- python importer.py "{input}"
```

程序参数通过独立列表传入。`{input}` 替换为当前样本的完整路径，`{python}` 可替换为运行本工具的 Python。命令里的空格参数请加引号。程序在 `--cwd` 指定的目录运行，省略时使用当前工作目录。

JSON 外层对象中的数组使用 JSON 指针定位，例如：

```console
python -m pandao_repro reduce --input input.json --format json --json-pointer /items --match E_INVALID_RULE --out result -- python validator.py "{input}"
```

使用能够区分目标错误的文字，避免只填写通用的 `Error`。默认从原始失败中读取退出码；程序正常退出但结果确实有问题时，可明确加 `--exit-code 0`。

首版默认输入和程序输出编码为 UTF-8，输入支持 UTF-8 字节顺序标记。其他编码可使用 `--encoding` 和 `--output-encoding` 指定。

## 结果和再次复现

输出目录包含：

- `缩减样本`：与原文件同名的缩减样本。
- `原始输入副本`：运行开始时的原始字节副本。
- `结论.md` 和 `结论.json`：缩减状态、保留位置、独立复现及逐项删除核对情况。
- `尝试记录.jsonl`：每次执行的退出码、错误匹配结果及有限长度的输出。
- `复现配置.json` 和 `复现.py`：在相同程序环境中再次复现。

安装本工具后，在结果目录运行：

```console
python 复现.py
```

复现入口需要原来的程序、依赖和工作目录；它不是整个软件环境的搬迁包。结果包含你的输入及程序输出，请按自己的资料分享范围处理。

## 使用范围

每次尝试都会实际执行指定命令。请选择本机测试环境里不修改输入、不向正式系统提交内容的复现命令。本工具仅在副本上缩减，不覆盖原文件，不覆盖已经存在的输出目录。

样本保留了能够触发目标错误的一组内容，并不等于已经查明根因。逐项删除核对通过表示每个保留项单独移除后都不能稳定触发指定错误，不保证找到了所有组合中全局最小的一组。

默认每次命令最多运行 10 秒，整个任务最多 300 秒、300 次执行。可用 `--timeout`、`--seconds`、`--max-tests` 调整。退出码 0 表示完成且核对通过；2 表示输入或执行条件错误；3 表示已有通过独立复现的样本，但缩减或最小性核对未完成；4 表示独立复现核对未完成或未通过。

许可证及原始来源见 `LICENSE.rst` 和 `THIRD_PARTY_NOTICES.md`。原版说明保留在 `README.rst`。
