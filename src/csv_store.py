"""CSV 存储：固定六列表头，按 url / 标题+作者 去重，增量追加。

字段口径（见 要求.txt）：
    title ≤100、author ≤50、category ≤20、description ≤200、url ≤500（字符数）
    rating 为浮点数、保留 1 位小数；平台未公布评分时记 0.0
"""

from __future__ import annotations

import csv
from pathlib import Path

FIELDS = ["title", "author", "category", "rating", "description", "url"]
MAX_LEN = {
    "title": 100,
    "author": 50,
    "category": 20,
    "description": 200,
    "url": 500,
}


def clean(text: str) -> str:
    """把换行/连续空白压成单空格，避免 CSV 里出现裸换行。"""
    return " ".join(str(text or "").split())


def format_rating(value) -> str:
    """统一成 1 位小数的字符串；无法解析或未知记 0.0。"""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "0.0"
    if not 0 < score <= 10:
        return "0.0"
    return f"{round(score, 1):.1f}"


def normalize(record: dict) -> dict:
    item = {}
    for field in FIELDS:
        text = clean(record.get(field, ""))
        limit = MAX_LEN.get(field)
        item[field] = text[:limit] if limit else text
    item["rating"] = format_rating(record.get("rating", 0))
    return item


class NovelCsv:
    """读写 novels.csv。已有行在初始化时载入内存用于去重。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._seen: set[str] = set()
        self.rows: list[dict] = []

        if self.path.exists():
            # 用 utf-8-sig 读是为了兼容历史文件里的 BOM，写入一律用纯 UTF-8
            with self.path.open("r", encoding="utf-8-sig", newline="") as fp:
                for row in csv.DictReader(fp):
                    item = normalize(row)
                    self.rows.append(item)
                    self._seen.add(self._key(item))
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # 要求.txt 指定 UTF-8：不加 BOM，否则 pandas 读到的首列名会带上 \ufeff
            with self.path.open("w", encoding="utf-8", newline="") as fp:
                csv.writer(fp).writerow(FIELDS)

    @staticmethod
    def _key(item: dict) -> str:
        if item["url"]:
            return item["url"]
        return f"{item['title']}::{item['author']}"

    def __len__(self) -> int:
        return len(self.rows)

    def add(self, records: list[dict]) -> int:
        """追加新记录，返回真正写入的条数（已存在或空标题的跳过）。"""
        fresh = []
        for record in records:
            item = normalize(record)
            if not item["title"] or not (item["description"] or item["author"]):
                continue
            key = self._key(item)
            if key in self._seen:
                continue
            self._seen.add(key)
            self.rows.append(item)
            fresh.append(item)

        if fresh:
            # 追加必须用 utf-8（不带 BOM），否则会在文件中间再插一个 BOM
            with self.path.open("a", encoding="utf-8", newline="") as fp:
                writer = csv.writer(fp)
                for item in fresh:
                    writer.writerow([item[field] for field in FIELDS])
        return len(fresh)
