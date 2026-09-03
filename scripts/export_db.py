"""把旧库里已抓取的小说导出到 novels.csv（六列格式）。

用法：
    python scripts/export_db.py --db "../小说推荐（一般）/data/novels.db" --csv novels.csv

字段映射：score → rating，intro → description，source_url → url。
豆瓣来源的条目会额外过滤掉教材/工具书等非小说（豆瓣是通用图书搜索）。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.csv_store import NovelCsv  # noqa: E402
from src.douban import NON_FICTION_PATTERN  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parents[2] / "小说推荐（一般）" / "data" / "novels.db"


def load(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT title, author, category, score, intro, source_url, source_platform FROM novels"
    ).fetchall()
    conn.close()

    records = []
    for row in rows:
        title = (row["title"] or "").strip()
        intro = (row["intro"] or "").strip()
        author = (row["author"] or "").strip()
        if not title or not (author or intro):
            continue
        # 豆瓣是通用图书搜索，会混进教材/工具书；这类冷门专业书几乎都没有评分，
        # 因此豆瓣来源只保留有评分的条目，其余按噪音丢弃
        if row["source_platform"] == "豆瓣读书" and (
            not (row["score"] or 0)
            or NON_FICTION_PATTERN.search(title)
            or NON_FICTION_PATTERN.search(intro)
        ):
            continue
        records.append(
            {
                "title": title,
                "author": author,
                "category": row["category"] or "",
                "rating": row["score"] or 0.0,
                "description": intro,
                "url": row["source_url"] or "",
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="导出旧库小说到 novels.csv")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument("--csv", type=Path, default=Path("novels.csv"), help="输出 CSV 路径")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"找不到数据库：{args.db}")

    records = load(args.db)
    store = NovelCsv(args.csv)
    added = store.add(records)
    print(f"读取 {len(records)} 条 → 新增 {added} 条 → {args.csv} 当前共 {len(store)} 条")


if __name__ == "__main__":
    main()
