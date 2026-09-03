"""起点中文网（移动端）爬虫。

实测结论（改动前请重新验证）：
* ``m.qidian.com`` 服务端直出，可直接解析；PC 版 ``www.qidian.com`` 返回 202 挑战页，不要用；
* 女频站 ``m.qdmm.com`` 同样返回 202，抓不到；
* 搜索页 20 条/关键词，**不支持分页**（``page``/``p``/``start`` 均无效），
  所以扩量靠「关键词 BFS」：搜索 → 拿到作者 → 用作者名再搜索；
* 分类页（``/category/catid*/subcatid*-male/``）每页 20 条，同样无分页，只取首页；
* 榜单页 9 个 slug，每个 20～50 条；
* 移动站点所有页面都没有评分字段，rating 记 0.0（表示未知）。

页面节点带 CSS Module 哈希，因此选择器一律用「属性包含」写法。
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.http import Fetcher

HOST = "https://m.qidian.com"
SEARCH_URL = f"{HOST}/search"
CATEGORY_INDEX_URL = f"{HOST}/category"
RANK_SLUGS = (
    "",
    "yuepiao",
    "hotsales",
    "readindex",
    "newfans",
    "rec",
    "update",
    "sign",
    "newbook",
    "newauthor",
)

STATUS_WORDS = ("连载", "完结", "完本", "已完成")


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _make(title, author, category, description, url) -> dict:
    return {
        "title": title,
        "author": author,
        "category": category,
        "rating": 0.0,
        "description": description,
        "url": url,
    }


class QidianCrawler:
    """起点中文网：搜索 / 榜单 / 分类页。"""

    platform = "起点中文网"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    # ── 卡面解析（搜索页 / 榜单页 / 分类页结构不同，这里统一兼容） ──────
    @staticmethod
    def _parse_card(node) -> dict | None:
        # 只认带哈希类名的标题节点，避免把「书友圈」「角色」之类的链接误当成书籍卡片
        title_node = node.select_one(
            "h2[class*=_searchBookName_], h2[class*=_bookTitle_], h2[class*=_title_]"
        )
        title = _text(title_node)
        if not title:
            return None

        desc_node = node.select_one(
            "p[class*=_bookDesc_], p[class*=_searchBookDesc_], p[class*=_bookSubTitle_]"
        )
        author_node = node.select_one("p[class*=_searchBookAuthor_], p[class*=_bookTip_]")
        author = author_node.get_text("", strip=True) if author_node else ""

        # 分类页：div[class*=_tags_] p 固定为 [分类, 状态, 字数]
        tags = [_text(p) for p in node.select("div[class*=_tags_] p")]
        category = next((t for t in tags if t and t not in STATUS_WORDS and "万字" not in t), "")

        if not author:
            # 榜单页：p[class*=_subTitle_] 形如「辰东 · 玄幻 · 394.58万字」
            meta = _text(node.select_one("p[class*=_subTitle_]"))
            parts = [p.strip() for p in meta.replace("·", "|").split("|") if p.strip()]
            parts = [p for p in parts if "万字" not in p and p not in STATUS_WORDS]
            if parts:
                author = parts[0]
                category = category or (parts[1] if len(parts) > 1 else "")

        href = node.get("href") or ""
        bid = (node.get("data-bid") or "").strip()
        if bid:
            url = f"{HOST}/book/{bid}/"
        elif href.startswith("//"):
            url = "https:" + href
        elif href.startswith("/"):
            url = HOST + href
        elif href.startswith("http"):
            url = href
        else:
            return None

        return _make(title, author, category, _text(desc_node), url)

    def _cards(self, soup: BeautifulSoup) -> list[dict]:
        # 搜索页卡片的 href 指向 /chapter/{bid}/0/（不含 /book/），只带 data-bid，
        # 所以除了 href 还要按卡片类名兜底
        records = []
        for node in soup.select(
            'a[href*="/book/"], a[class*=_listItem_], a[class*=_bookWrapper_]'
        ):
            record = self._parse_card(node)
            if record:
                records.append(record)
        return records

    def _dedup(self, records: list[dict]) -> list[dict]:
        seen, out = set(), []
        for record in records:
            if record["url"] in seen:
                continue
            seen.add(record["url"])
            out.append(record)
        return out

    # ── 对外接口 ────────────────────────────────────────────────────────
    def search(self, keyword: str) -> list[dict]:
        """按关键词搜索，一次最多 20 条（无分页）。"""
        html = self.fetcher.get(SEARCH_URL, params={"kw": keyword})
        if not html:
            return []
        return self._dedup(self._cards(BeautifulSoup(html, "lxml")))

    def rank(self, slug: str = "") -> list[dict]:
        url = f"{HOST}/rank/{slug}/" if slug else f"{HOST}/rank"
        html = self.fetcher.get(url)
        if not html:
            return []
        return self._dedup(self._cards(BeautifulSoup(html, "lxml")))

    def all_ranks(self) -> list[dict]:
        records = []
        for slug in RANK_SLUGS:
            records.extend(self.rank(slug))
        return self._dedup(records)

    def category_pages(self) -> list[dict]:
        """抓分类索引里的每个子分类首页（每页 20 条）。"""
        html = self.fetcher.get(CATEGORY_INDEX_URL)
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")

        links = set()
        for node in soup.select('a[href*="/category/"]'):
            href = (node.get("href") or "").strip()
            if "subcatid" not in href:
                continue
            links.add(href if href.startswith("http") else "https:" + href)

        records = []
        for link in sorted(links):
            page = self.fetcher.get(link)
            if not page:
                continue
            records.extend(self._cards(BeautifulSoup(page, "lxml")))
        return self._dedup(records)
