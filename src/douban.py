"""豆瓣读书爬虫（评分补充源）。

实测结论：
* 搜索结果在内嵌 ``window.__DATA__`` 里，后面还跟有别的语句，
  必须用 ``json.JSONDecoder().raw_decode`` 只取第一段完整对象；
* 支持 ``start=0/15/30`` 分页，15 条/页，是三个平台里唯一能翻页的；
* ``rating.value`` 是 10 分制，正好补上起点/潇湘缺失的评分；
* 它是通用图书搜索，会混进教材/工具书，用 ``NON_FICTION_PATTERN`` 过滤；
* 搜索结果只有出版信息没有简介，简介需要再取一次 ``/subject/{id}/`` 详情页。
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from src.http import Fetcher

SEARCH_URL = "https://search.douban.com/book/subject_search"
SUBJECT_URL = "https://book.douban.com/subject/{sid}/"
DATA_PATTERN = re.compile(r"window\.__DATA__\s*=\s*(\{.*?\})\s*</script>", re.S)

# 豆瓣是通用图书搜索，命中即丢弃（命中不准时改这里）
NON_FICTION_PATTERN = re.compile(
    "写作|教程|教材|研究|理论|导论|概论|词典|辞典|百科|手册|全集|选集|文集|年鉴|"
    "白皮书|指南|入门|原理|方法论|散文集|诗集|剧本|画册|图鉴|攻略|杂志|期刊|"
    "自传|传记|回忆录|讲稿|译丛|试题|考研|四级|六级|语文|数学|英语|物理|化学"
)


class DoubanCrawler:
    """豆瓣读书：分页搜索 + 详情页简介。"""

    platform = "豆瓣读书"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    def _items(self, keyword: str, start: int) -> list[dict]:
        html = self.fetcher.get(
            SEARCH_URL, params={"search_text": keyword, "cat": "1001", "start": start}
        )
        if not html:
            return []
        match = DATA_PATTERN.search(html)
        if not match:
            return []
        try:
            payload, _ = json.JSONDecoder().raw_decode(match.group(1))
        except json.JSONDecodeError:
            return []
        return [i for i in payload.get("items", []) if i.get("tpl_name") == "search_subject"]

    @staticmethod
    def _author(abstract: str) -> str:
        return abstract.split("/")[0].strip() if abstract else ""

    def _detail(self, url: str) -> str:
        """取详情页的「内容简介」；拿不到返回空串。"""
        html = self.fetcher.get(url)
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")

        # related_info 下依次是「内容简介」「作者简介」，取第一个才是简介正文
        blocks = soup.select("div.related_info div.intro")
        return blocks[0].get_text(" ", strip=True) if blocks else ""

    @staticmethod
    def _category(keyword: str) -> str:
        """豆瓣不返回分类（标签区需登录才渲染），用搜索关键词推导题材。"""
        return keyword[: -2] if keyword.endswith("小说") and len(keyword) > 2 else keyword

    def search(self, keyword: str, pages: int = 3, with_detail: bool = True) -> list[dict]:
        """按关键词分页搜索；with_detail=True 时逐条取详情页补简介。"""
        records = []
        for page in range(pages):
            for item in self._items(keyword, page * 15):
                title = (item.get("title") or "").strip()
                abstract = (item.get("abstract") or "").strip()
                if not title:
                    continue
                if NON_FICTION_PATTERN.search(title) or NON_FICTION_PATTERN.search(abstract):
                    continue

                rating = item.get("rating") or {}
                # 无评分的豆瓣条目基本都是冷门教材/专业书（豆瓣是通用图书搜索），直接丢
                if not rating.get("value"):
                    continue

                url = (item.get("url") or "").strip()

                intro = self._detail(url) if (with_detail and url) else ""

                records.append(
                    {
                        "title": title,
                        "author": self._author(abstract),
                        "category": self._category(keyword),
                        "rating": rating.get("value") or 0.0,
                        "description": intro or abstract,
                        "url": url,
                    }
                )
        return records
