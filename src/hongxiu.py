"""红袖书院（阅文女频 + 男频书库）爬虫。

实测结论（2026-09-03）：
* ``/category/...`` 是服务端直出，40 条/页，**支持分页**（末位数字即页码），
  「全部」分类有 50 页以上，是量最大的单一入口；
* 单条结果自带书名、作者、分类、状态、字数与简介，不需要 N+1 条详情请求，
  比潇湘（必须逐本取详情）省一个数量级的请求；
* 榜单页只有书名和链接（无作者/简介），够不上入库标准，所以不抓榜单；
* 没有评分字段，rating 记 0.0（表示未知）。
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.http import Fetcher

HOST = "https://www.hongxiu.com"
# f1 全占位的 URL 即「不筛选」，末位是页码
ALL_URL = HOST + "/category/f1_f1_f1_f1_f1_f1_0_{page}"
CATEGORY_INDEX_URL = HOST + "/category"


class HongxiuCrawler:
    """红袖书院：全部/分类分页 + 榜单页。"""

    platform = "红袖书院"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    @staticmethod
    def _parse_li(li) -> dict | None:
        title_node = li.select_one("h3 a[href*='/book/']") or li.select_one("a[href*='/book/']")
        if not title_node:
            return None

        href = (title_node.get("href") or "").strip()
        if not href:
            return None
        url = href if href.startswith("http") else HOST + href

        title = (title_node.get("title") or "").strip() or title_node.get_text(strip=True)
        if not title:
            return None

        author_node = li.select_one("h4 a, h4")
        tags = [span.get_text(strip=True) for span in li.select("p.tag span")]
        intro_node = li.select_one("p.intro")

        return {
            "title": title,
            "author": author_node.get_text(strip=True) if author_node else "",
            "category": next((t for t in tags if t and "万" not in t and t not in ("连载中", "已完结")), ""),
            "rating": 0.0,
            "description": intro_node.get_text(" ", strip=True) if intro_node else "",
            "url": url,
        }

    def _page(self, url: str) -> list[dict]:
        html = self.fetcher.get(url)
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")

        records, seen = [], set()
        for li in soup.select("li"):
            record = self._parse_li(li)
            if record and record["url"] not in seen:
                seen.add(record["url"])
                records.append(record)
        return records

    def all_pages(self, pages: int = 20) -> list[dict]:
        """抓「全部」分类的前 pages 页。"""
        records = []
        for page in range(1, pages + 1):
            records.extend(self._page(ALL_URL.format(page=page)))
        return records

    def category_pages(self, pages: int = 5, max_categories: int = 30) -> list[dict]:
        """按分类索引逐个分类翻页。"""
        html = self.fetcher.get(CATEGORY_INDEX_URL)
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")

        links = set()
        for node in soup.select("a[href^='/category/']"):
            href = (node.get("href") or "").strip()
            # 只取一级分类（形如 /category/30020_f1_f1_f1_f1_f1_0_1），跳过带筛选条件的组合
            parts = href.split("/")[-1].split("_")
            if len(parts) != 8 or parts[1] != "f1" or parts[-2] != "0":
                continue
            links.add(HOST + href)

        records = []
        for link in sorted(links)[:max_categories]:
            stem = link.rsplit("_", 1)[0]
            for page in range(1, pages + 1):
                records.extend(self._page(f"{stem}_{page}"))
        return records
