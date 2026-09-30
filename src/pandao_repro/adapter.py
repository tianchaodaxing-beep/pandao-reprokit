"""保留文本行、CSV 表头与 JSON 外层结构。"""
import copy
import csv
import io
import json


class TaskError(ValueError):
    """使用者可以处理的输入或执行错误。"""


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise TaskError(f"JSON 含重复键，无法无损重建：{key}")
        result[key] = value
    return result


def _constant(value):
    raise TaskError(f"JSON 含不符合标准的值：{value}")


class Adapter:
    def __init__(self, raw, *, kind="lines", encoding="utf-8", delimiter=",", pointer=""):
        self.kind, self.encoding = kind, encoding
        if encoding.lower().replace("_", "-") in {"utf-8", "utf8"} and raw.startswith(b"\xef\xbb\xbf"):
            self.encoding = "utf-8-sig"
        try:
            self.text = raw.decode(self.encoding)
        except (UnicodeDecodeError, LookupError) as error:
            raise TaskError("文件无法按指定编码读取，请检查 --encoding") from error
        if kind == "lines":
            self.units = self.text.splitlines(keepends=True)
        elif kind == "csv":
            if len(delimiter) != 1 or delimiter in '\r\n"':
                raise TaskError("CSV 分隔符必须是一个有效字符")
            self.delimiter = delimiter
            try:
                rows = list(csv.reader(io.StringIO(self.text, newline=""), delimiter=delimiter, strict=True))
            except csv.Error as error:
                raise TaskError(f"CSV 无法读取：{error}") from error
            if not rows:
                raise TaskError("CSV 没有表头")
            self.header, self.units = rows[0], rows[1:]
            self.line_ending = "\r\n" if "\r\n" in self.text else "\n"
        elif kind == "json":
            try:
                self.document = json.loads(self.text, object_pairs_hook=_pairs, parse_constant=_constant)
            except json.JSONDecodeError as error:
                raise TaskError(f"JSON 无法读取：第 {error.lineno} 行，第 {error.colno} 列") from error
            if pointer and not pointer.startswith("/"):
                raise TaskError("--json-pointer 必须为空或以 / 开头")
            self.parts = [] if not pointer else [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]
            if any("~" in p.replace("~0", "").replace("~1", "") for p in pointer.split("/")[1:]):
                raise TaskError("JSON 指针含无效转义")
            current = self.document
            for part in self.parts:
                current = self._get(current, part)
            if not isinstance(current, list):
                raise TaskError("JSON 指针必须指向数组；根数组可省略 --json-pointer")
            self.units = current
        else:
            raise TaskError(f"不支持的格式：{kind}")

    @staticmethod
    def _get(container, part):
        try:
            if isinstance(container, list):
                if not part.isdigit() or (len(part) > 1 and part.startswith("0")):
                    raise TaskError("JSON 数组下标无效")
                return container[int(part)]
            if isinstance(container, dict):
                return container[part]
        except (KeyError, IndexError) as error:
            raise TaskError(f"JSON 指针找不到位置：{part}") from error
        raise TaskError("JSON 指针经过了非容器值")

    def build(self, indexes):
        values = [self.units[i] for i in indexes]
        if self.kind == "lines":
            text = "".join(values)
        elif self.kind == "csv":
            output = io.StringIO(newline="")
            writer = csv.writer(output, delimiter=self.delimiter, lineterminator=self.line_ending)
            writer.writerow(self.header)
            writer.writerows(values)
            text = output.getvalue()
        else:
            document = copy.deepcopy(self.document)
            if not self.parts:
                document = values
            else:
                parent = document
                for part in self.parts[:-1]:
                    parent = self._get(parent, part)
                last = self.parts[-1]
                parent[int(last) if isinstance(parent, list) else last] = values
            text = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        return text.encode(self.encoding)
