"""抓取小说并增量写入 novels.csv（六列格式）。

用法：
    python scripts/crawl.py                       # 全量跑（起点→潇湘→豆瓣）
    python scripts/crawl.py --skip douban         # 跳过豆瓣
    python scripts/crawl.py --keyword-limit 100   # 限制起点关键词个数

扩量思路：起点搜索页不支持分页，靠「关键词 BFS」扩量 —— 搜索关键词 →
拿到书籍作者 → 用作者名再搜索 → 拿到更多书与作者，直到用满关键词预算。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.csv_store import NovelCsv  # noqa: E402
from src.douban import DoubanCrawler  # noqa: E402
from src.hongxiu import HongxiuCrawler  # noqa: E402
from src.http import Fetcher  # noqa: E402
from src.qidian import QidianCrawler  # noqa: E402
from src.xxsy import XxsyCrawler  # noqa: E402

# 起点搜索种子：题材词 + 流派词 + 知名作者名（搜作者名会返回其作品）
SEED_KEYWORDS = [
    # 题材 / 分类
    "玄幻", "奇幻", "都市", "仙侠", "科幻", "历史", "军事", "游戏", "竞技", "悬疑",
    "推理", "灵异", "恐怖", "盗墓", "轻小说", "二次元", "同人", "无限流", "系统流",
    "穿越", "重生", "废土", "末世", "机甲", "星际", "修真", "洪荒", "武侠", "江湖",
    "权谋", "宫斗", "宅斗", "种田", "年代", "豪门", "职场", "商战", "娱乐圈", "校园",
    "青春", "电竞", "网游", "副本", "异界", "魔法", "剑道", "武道", "兵王", "神医",
    "相师", "鉴宝", "美食", "足球", "篮球", "赛车", "赛博朋克", "克苏鲁", "蒸汽朋克",
    "民俗", "探险", "法医", "刑侦", "医生", "律师", "教师", "工匠", "科举", "大唐",
    "大明", "大宋", "大秦", "三国", "民国", "抗战", "谍战", "特种兵", "佣兵", "杀手",
    "特工", "异能", "超能力", "进化", "丧尸", "血族", "狼人", "妖怪", "鬼怪", "神话",
    "封神", "西游", "聊斋", "上古", "宗门", "家族", "门派", "学院", "召唤", "契约",
    "卡牌", "基建", "经营", "直播", "文娱", "明星", "网红", "盗墓笔记", "鬼吹灯",
    "古言", "现言", "古代言情", "现代言情", "总裁", "甜宠", "虐恋", "先婚后爱",
    "青梅竹马", "闪婚", "替嫁", "太子妃", "王妃", "嫡女", "庶女", "公主", "摄政王",
    "王爷", "将军", "丞相", "师徒", "师尊", "魔尊", "女强", "逆袭", "复仇", "快穿",
    "穿书", "团宠", "马甲", "医妃", "仵作", "宅门", "世家", "绣女", "影后", "歌后",
    # 起点知名作者（用作者名搜索可拿到其全部作品）
    "辰东", "唐家三少", "天蚕土豆", "我吃西红柿", "猫腻", "爱潜水的乌贼", "会说话的肘子",
    "烽火戏诸侯", "血红", "跳舞", "忘语", "耳根", "梦入神机", "风凌天下", "萧鼎",
    "烟雨江南", "酒徒", "孑与2", "愤怒的香蕉", "更俗", "横扫天涯", "宅猪", "骷髅精灵",
    "方想", "蝴蝶蓝", "三天两觉", "国王陛下", "远瞳", "卧牛真人", "齐橙", "志鸟村",
    "卓牧闲", "吉祥夜", "叶非夜", "天下霸唱", "南派三叔", "沧月", "匪我思存", "顾漫",
    "桐华", "流潋紫", "海宴", "吱吱", "关心则乱", "月下蝶影", "随侯珠", "尾鱼",
    "唐家三少", "净无痕", "妖夜", "鹅是老五", "玄色", "天衣有风", "墨舞碧歌",
]

# 豆瓣关键词：它是通用图书搜索，用「XX小说」这类词命中率最高
DOUBAN_KEYWORDS = [
    "科幻小说", "悬疑小说", "推理小说", "言情小说", "武侠小说", "历史小说",
    "奇幻小说", "青春小说", "网络小说", "仙侠小说", "恐怖小说", "盗墓小说",
    "军事小说", "职场小说", "架空历史小说", "侦探小说", "官场小说", "玄幻小说",
    "当代小说", "长篇小说", "外国小说", "日本小说", "英国小说", "法国小说",
    "都市小说", "灵异小说", "惊悚小说", "冒险小说", "校园小说", "文学小说",
]


def crawl_qidian(
    store: NovelCsv, keyword_limit: int, delay: float, logger, with_lists: bool = True
) -> None:
    qidian = QidianCrawler(Fetcher(delay=delay))

    if with_lists:
        logger.info("[起点] 抓榜单页 …")
        store.add(qidian.all_ranks())
        logger.info("[起点] 榜单完成，CSV 共 %s 条", len(store))

        logger.info("[起点] 抓分类页 …")
        store.add(qidian.category_pages())
        logger.info("[起点] 分类页完成，CSV 共 %s 条", len(store))

    logger.info("[起点] 关键词 BFS（上限 %s 个关键词）…", keyword_limit)
    queue = deque(SEED_KEYWORDS)
    seen = set(queue)
    processed = 0
    empty_streak = 0
    cooldowns = 0

    while queue and processed < keyword_limit:
        keyword = queue.popleft()
        processed += 1

        records = qidian.search(keyword)
        added = store.add(records)
        if processed % 20 == 0 or added:
            logger.info(
                "[起点] %s/%s kw=%s 新书+%s 累计 %s",
                processed, keyword_limit, keyword, added, len(store),
            )

        # 起点限流时会连续返回 403，硬重试只会把 IP 封更久，改成整段冷却
        empty_streak = empty_streak + 1 if not records else 0
        if empty_streak >= 15:
            cooldowns += 1
            if cooldowns > 2:
                logger.warning("[起点] 冷却两次后仍拿不到数据，疑似 IP 被封，结束起点抓取")
                break
            logger.warning("[起点] 连续 %s 个关键词无数据，冷却 120 秒", empty_streak)
            time.sleep(120)
            empty_streak = 0

        # 用作者名继续扩关键词（作者名搜索会返回该作者的作品）
        for record in records:
            author = record["author"]
            if author and author not in seen and len(seen) < keyword_limit * 3:
                seen.add(author)
                queue.append(author)


def crawl_xxsy(store: NovelCsv, delay: float, logger) -> None:
    xxsy = XxsyCrawler(Fetcher(delay=delay))
    logger.info("[潇湘] 抓榜单 + 逐本详情（较慢）…")
    store.add(xxsy.crawl())
    logger.info("[潇湘] 完成，CSV 共 %s 条", len(store))


def crawl_hongxiu(store: NovelCsv, pages: int, all_pages: int, delay: float, logger) -> None:
    hongxiu = HongxiuCrawler(Fetcher(delay=delay))

    logger.info("[红袖] 抓「全部」分类前 %s 页 …", all_pages)
    store.add(hongxiu.all_pages(pages=all_pages))
    logger.info("[红袖] 全部完成，CSV 共 %s 条", len(store))

    logger.info("[红袖] 逐分类抓 %s 页/分类 …", pages)
    store.add(hongxiu.category_pages(pages=pages))
    logger.info("[红袖] 分类完成，CSV 共 %s 条", len(store))


def crawl_douban(store: NovelCsv, keywords: int, pages: int, delay: float, logger) -> None:
    # 豆瓣限流比起点严，间隔至少 1.2 秒
    delay = max(delay, 1.2)
    douban = DoubanCrawler(Fetcher(delay=delay))

    empty_streak = 0
    for index, keyword in enumerate(DOUBAN_KEYWORDS[:keywords], 1):
        added = store.add(douban.search(keyword, pages=pages))
        logger.info(
            "[豆瓣] %s/%s kw=%s 新增 %s 条，CSV 共 %s 条",
            index, keywords, keyword, added, len(store),
        )
        empty_streak = empty_streak + 1 if not added else 0
        if empty_streak >= 3:
            logger.warning("[豆瓣] 连续 %s 个关键词无新增，疑似被限流，提前结束", empty_streak)
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取小说写入 novels.csv")
    parser.add_argument("--csv", type=Path, default=Path("novels.csv"))
    parser.add_argument("--delay", type=float, default=0.6, help="每次请求后的间隔秒数")
    parser.add_argument("--keyword-limit", type=int, default=250, help="起点关键词 BFS 上限")
    parser.add_argument("--douban-keywords", type=int, default=30, help="豆瓣关键词个数")
    parser.add_argument("--douban-pages", type=int, default=2, help="每个豆瓣关键词翻页数")
    parser.add_argument("--hongxiu-pages", type=int, default=8, help="红袖每个分类抓几页")
    parser.add_argument("--hongxiu-all-pages", type=int, default=30, help="红袖「全部」分类抓几页")
    parser.add_argument(
        "--skip", nargs="*", default=[], choices=["qidian", "xxsy", "douban", "hongxiu"]
    )
    parser.add_argument("--no-lists", action="store_true", help="跳过起点榜单页与分类页")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )
    logger = logging.getLogger("crawl")

    store = NovelCsv(args.csv)
    logger.info("起点状态：%s（%s 行）", args.csv, len(store))

    if "qidian" not in args.skip:
        crawl_qidian(store, args.keyword_limit, args.delay, logger, with_lists=not args.no_lists)
    if "hongxiu" not in args.skip:
        crawl_hongxiu(store, args.hongxiu_pages, args.hongxiu_all_pages, args.delay, logger)
    if "xxsy" not in args.skip:
        crawl_xxsy(store, args.delay, logger)
    if "douban" not in args.skip:
        crawl_douban(store, args.douban_keywords, args.douban_pages, args.delay, logger)

    logger.info("抓取结束：%s 共 %s 条", args.csv, len(store))


if __name__ == "__main__":
    main()
