# PANDAO reproduction toolkit

[简体中文](README.md) · English

A workflow built on [Picire](https://github.com/renatahodovan/picire) for reducing a failing input to a smaller sample that still reproduces the same failure.

For local command-line import or text-processing errors with a stable failure signal. Supports text lines, CSV with preserved headers and records in a selected JSON array.

## Added workflow

- Specify the original command, failure text and exit code without writing a separate predicate script.
- Preserve CSV headers or a JSON array's outer object and unrelated content.
- Check both the original input and its reconstructed form before reducing.
- Independently reproduce the final failure three times and check single-item deletion.
- Save the original copy, retained positions, attempt records, summaries and a replay entry point.
- Bound attempts and total time, retaining current results when a limit is reached.

Picire's original modules remain in `src/picire`; PANDAO's workflow is in `src/pandao_repro`. The original authors' copyright, license and source notices remain. This project does not imply endorsement by the original authors.

[Source](https://github.com/tianchaodaxing-beep/pandao-reprokit) · [Download](https://github.com/tianchaodaxing-beep/pandao-reprokit/releases/latest)

## Install and try

Requires Python 3.10 or later. Create a virtual environment and install:

```sh
python -m venv .venv
```

Windows:

```console
.venv\Scripts\python -m pip install .
.venv\Scripts\python -m pandao_repro --lang en demo
```

Linux or macOS:

```sh
.venv/bin/python -m pip install .
.venv/bin/python -m pandao_repro --lang en demo
```

Windows also includes `Run-demo.cmd`. The demo uses explicitly simulated records, without real business data. Use `--lang zh` or `--lang en` before the subcommand. Original machine-readable results and source data remain unchanged; an English metadata summary is added as `Summary.en.md`.

## Your own command

```sh
python -m pandao_repro --lang en reduce --input input.csv --format csv --match E_RULE_COLLISION --out results -- python importer.py "{input}"
```

Arguments are passed directly as a list. `{input}` becomes the candidate sample's full path; `{python}` can represent the running Python interpreter. Quote arguments containing spaces. `--cwd` sets the working directory; otherwise the current directory is used.

Use a JSON pointer for a nested record array:

```sh
python -m pandao_repro --lang en reduce --input input.json --format json --json-pointer /items --match E_INVALID_RULE --out results -- python validator.py "{input}"
```

Choose specific failure text, rather than a generic “Error”. The exit code defaults to the original failure; explicitly use `--exit-code 0` if a program returns success despite an incorrect result. Input and program output default to UTF-8, with input byte-order marks supported. Use `--encoding` and `--output-encoding` for other encodings.

## Results and replay

| File or folder | Purpose |
|---|---|
| `缩减样本` | Reduced sample, retaining the original file name |
| `原始输入副本` | Original byte copy |
| `结论.md`, `结论.json` | Reduction status, retained positions, reproduction and deletion checks |
| `Summary.en.md` | English task metadata |
| `尝试记录.jsonl` | Attempt exit codes, marker results and bounded output |
| `复现配置.json`, `复现.py` | Replay in the original program environment |

```sh
python results/复现.py
```

Replay still needs the original program, dependencies and working directory. It is not a complete environment transfer package. Results include your input and program output; choose your sharing scope accordingly.

## Scope and exit codes

Every attempt actually executes the given command. Use a local test command that does not modify input or submit to production systems. Reduction operates on copies; original files and existing result directories are not overwritten.

A reduced sample does not establish the root cause. Successful single-item deletion checks do not guarantee the globally smallest combination.

Defaults: 10 seconds per command, 300 seconds overall and 300 executions. Adjust `--timeout`, `--seconds` and `--max-tests` as needed.

| Exit code | Meaning |
|---|---|
| 0 | Complete, with checks passed |
| 2 | Invalid input or execution conditions |
| 3 | Independently reproduced sample exists; reduction or deletion checks are incomplete |
| 4 | Independent reproduction is incomplete or failed |

See `LICENSE.rst` and `THIRD_PARTY_NOTICES.md`. Picire's original English documentation is retained in `README.rst`.
