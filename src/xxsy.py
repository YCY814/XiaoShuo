"""潇湘书院（女频）爬虫。

实测结论：
* ``/search?keyword=`` 与 ``/category/*.html`` 均为前端渲染空壳，抓不到；
* 服务端直出的是榜单页 ``/rank``、``/rank/finish``（各 50 条）和首页（约 40 条）；
* 简介、分类需要再取一次 ``/book/{id}`` 详情页（N+1 请求，是三个平台里最慢的）；
* 潇湘不提供评分，rating 记 0.0（表示未知）；
* 部分 bookId 会偶发 500，属正常，跳过即可。
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from src.http import Fetcher

HOST = "https://www.xxsy.net"
LIST_URLS = (
    f"{HOST}/rank",
    f"{HOST}/rank/finish",
    HOST + "/",
)


class XxsyCrawler:
    """潇湘书院：榜单 + 详情页补全。"""

    platform = "潇湘书院"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    def _list(self) -> list[dict]:
        """从榜单页/首页收集 {title, author, url}，按 url 去重。"""
        seen, items = set(), []
        for url in LIST_URLS:
            html = self.fetcher.get(url)
            if not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            for li in soup.select("li[data-bookid]"):
                link = li.select_one("a[href^='/book/']")
                if not link:
                    continue
                href = (link.get("href") or "").strip()
                if href in seen:
                    continue
                seen.add(href)
                author_node = li.select_one("span.piao")
                items.append(
                    {
                        "title": link.get_text(strip=True),
                        "author": author_node.get_text(strip=True) if author_node else "",
                        "url": HOST + href,
                    }
                )
        return items

    def _detail(self, item: dict) -> dict | None:
        html = self.fetcher.get(item["url"])
        if not html:
            return None
        soup = BeautifulSoup(html, "lxml")
        profile = soup.select_one("div.bookdetail")
        if not profile:
            return None

        title_node = profile.select_one(".title h1")
        title = title_node.get_text(strip=True) if title_node else item["title"]
        if not title:
            return None

        author = item["author"]
        author_span = profile.select_one(".title span")
        if author_span:
            match = re.search(r"文\s*/\s*(.+)", author_span.get_text(strip=True))
            if match:
                author = match.group(1).strip()

        category = ""
        for col in profile.select("p.sub-cols span"):
            text = col.get_text(strip=True)
            if text.startswith("类别："):
                category = text.replace("类别：", "").strip()
                break

        intro = ""
        tab = soup.select_one("div.book-detail-tab")
        if tab:
            # tab 容器里还挂着「作品介绍 / 作品目录」两个页签标题，正文在 click-bd 里
            body = tab.select_one("div.click-bd") or tab
            intro = body.get_text(" ", strip=True)
            for prefix in ("作品介绍", "作品目录"):
                if intro.startswith(prefix):
                    intro = intro[len(prefix):].strip()
                    break

        return {
            "title": title,
            "author": author,
            "category": category,
            "rating": 0.0,
            "description": intro,
            "url": item["url"],
        }

    def crawl(self, limit: int = 0) -> list[dict]:
        """抓榜单并对每本书补全详情；limit>0 时最多返回 limit 条。"""
        records = []
        for item in self._list():
            if limit and len(records) >= limit:
                break
            record = self._detail(item)
            if record:
                records.append(record)
        return records
