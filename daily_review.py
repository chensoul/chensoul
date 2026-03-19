#!/usr/bin/env python3
"""
每日简报生成脚本（一体版）。
包含：日期、天气(wttr.in)、今日待办(GitHub Issues)、今日指数/诗词/名言/Trending、WakaTime、跑步距离、昨日收藏(Linkding)、Hacker News。

今日待办：GitHub Issues（GITHUB_TOKEN + owner：优先 GITHUB_USERNAME，否则脚本所在目录名，拉取 {owner}/{owner} 仓库的 open issues）。
昨日收藏：需配置 LINKDING_URL（如 https://linkding.chensoul.cc）、LINKDING_TOKEN（Linkding API Token）。
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlparse

# Asia/Shanghai = UTC+8
TZ_SHANGHAI = timezone(timedelta(hours=8))

def _load_env(path):
    """从 .env 文件加载 KEY=VALUE 到 os.environ（仅标准库，不覆盖已存在的变量）。"""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"").replace("\\n", "\n")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


# 默认加载同目录 .env（BRIEFING_*、GITHUB_TOKEN 等）
_script_dir = os.path.dirname(os.path.abspath(__file__))
_load_env(os.path.join(_script_dir, ".env"))

# 日志输出到 stderr，不影响 stdout（管道或 -o 文件）
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# --- 常量 ---
WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
WEATHER_CONDITION_ZH = {
    "Clear": "晴朗", "Sunny": "晴朗",
    "Partly cloudy": "多云", "Partly Cloudy": "多云",
    "Cloudy": "阴天", "Overcast": "阴沉",
    "Mist": "雾", "Fog": "雾", "Haze": "雾霾",
    "Light rain": "小雨", "Patchy rain possible": "小雨",
    "Moderate rain": "中雨", "Heavy rain": "大雨",
    "Light snow": "小雪", "Moderate snow": "中雪", "Heavy snow": "大雪",
    "Thundery outbreaks possible": "可能有雷暴",
}
WTTR_URL = "https://wttr.in/{city}?format=j1"
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
HN_MIN_SCORE = 50
HN_MAX_ITEMS = 5
SENTENCE_API = "https://v1.jinrishici.com/all.json"
QUOTE_API = "https://api.shadiao.pro/du"
EASTMONEY_GOLD_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_GOLD_SECID = "118.AU9999"
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
GITHUB_TRENDING_BASE = "https://github.com/trending"
LINKDING_API_BOOKMARKS = "/api/bookmarks/"
LINKDING_TITLE_MAX = 50  # 书签标题最大字符数，超出截断


def _safe_get(url, params=None, headers=None, timeout=10):
    """HTTP GET，返回 (resp, None) 或 (None, error)。resp 有 .text, .content, .status_code, .json()。"""
    try:
        if params:
            url = url + ("&" if "?" in url else "?") + urlencode(params)
        h = {"User-Agent": "DailyBriefing/1.0"}
        if headers:
            h.update(headers)
        req = Request(url, headers=h)
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        code = resp.status if hasattr(resp, "status") else 200

        class _Resp:
            def __init__(self, text, status_code):
                self.text = text
                self.status_code = status_code
                self.content = text.encode("utf-8")
            def json(self):
                return json.loads(self.text)
        return _Resp(body, code), None
    except Exception as e:
        return None, str(e)


# ---------- 1. 标题与日期 ----------
def header():
    t = datetime.now(TZ_SHANGHAI)
    date_str = t.strftime("%Y年%m月%d日")
    wd = WEEKDAY_ZH[t.weekday()]
    first_line = "# 📅 每日简报 - {} {}".format(date_str, wd)
    try:
        start = t.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        day_of_year = (t - start).days + 1
        year = t.year
        is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
        total = 366 if is_leap else 365
        remaining = total - day_of_year
        pct_str = f"{(day_of_year / total) * 100:.1f}%"
        second_line = "{} 年已过去 {} ({}/{})，今年还剩下 {} 天，要珍惜时间哦！".format(year, pct_str, day_of_year, total, remaining)
        return first_line + "\n\n" + second_line
    except Exception:
        return first_line


# ---------- 2. 天气 (wttr.in) ----------
def weather_line():
    """返回单行天气内容：Wuhan：多云, 12°C - 21°C（中文逗号）。"""
    city = os.environ.get("WEATHER_CITY", "Wuhan")
    logger.info("获取天气: %s", city)
    url = WTTR_URL.format(city=city)
    try:
        r, err = _safe_get(url, timeout=15)
        if err or not r:
            logger.warning("天气获取失败: %s", err or "无响应")
            return ""
        data = r.json()
        curr = (data.get("current_condition") or [{}])[0]
        descs = curr.get("weatherDesc") or [{}]
        cond_en = (descs[0].get("value") or "").strip()
        weathers = data.get("weather") or [{}]
        day = weathers[0]
        min_t = day.get("mintempC", "N/A")
        max_t = day.get("maxtempC", "N/A")
        cond = WEATHER_CONDITION_ZH.get(cond_en, cond_en)
        result = "{}：{}，{}°C - {}°C".format(city, cond, min_t, max_t)
        logger.info("天气: %s", result)
        return result
    except Exception as e:
        logger.warning("天气解析失败: %s", e)
        return ""


# ---------- 3. 今日待办：GitHub Issues ----------

def tasks_section():
    """从 GitHub {owner}/{owner} 拉取 open issues 作为今日任务，返回整块 Markdown。"""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    owner = (os.environ.get("GITHUB_USERNAME", "").strip() or (os.path.basename(_script_dir) if _script_dir else ""))
    if not token or not owner:
        logger.info("今日任务: 未配置 GITHUB_TOKEN 或 owner，跳过")
        return "## 📋 今日任务\n\n- 任务功能未配置（需 GITHUB_TOKEN 且在项目目录下运行）"
    repo = "{}/{}".format(owner, owner)
    logger.info("今日任务: 拉取 %s open issues", repo)
    headers = {"Authorization": "Bearer {}".format(token), "Accept": "application/vnd.github.v3+json"}
    r, err = _safe_get("https://api.github.com/repos/{}/issues".format(repo), params={"state": "open", "per_page": 20}, headers=headers, timeout=15)
    if err or not r:
        logger.warning("GitHub Issues 请求失败: %s", err or "无响应")
        return "## 📋 今日任务\n\n- {}".format(err or "请求失败")
    if r.status_code != 200:
        logger.warning("GitHub Issues 返回 %s", r.status_code)
        return "## 📋 今日任务\n\n- HTTP {}".format(r.status_code)
    try:
        data = r.json()
        items = data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("GitHub Issues 解析失败: %s", e)
        return "## 📋 今日任务\n\n- 解析失败"
    issues = [
        i for i in items
        if i.get("pull_request") is None and (i.get("title") or "").strip() != "Dependency Dashboard"
    ][:20]
    if not issues:
        logger.info("今日任务: 无待办，共 0 条")
        return "## 📋 今日任务\n\n- 没有待办任务，轻松的一天！"
    logger.info("今日任务: 共 %d 条", len(issues))
    lines = ["- [{}]({})".format((i.get("title") or "无标题").strip(), i.get("html_url", "")) for i in issues]
    return "## 📋 今日任务\n\n" + "\n".join(lines)


# ---------- 4. 更多资讯（指数/诗词/名言/Trending/WakaTime/跑步）----------
def poem_line():
    """今日诗词单行：诗句。 —— 作者, 《诗名》（用于今日概览）。"""
    try:
        r, err = _safe_get(SENTENCE_API, timeout=10)
        if err or not r:
            return ""
        data = r.json()
        content = (data.get("content") or "").strip()
        origin = (data.get("origin") or "").strip()
        author = (data.get("author") or "").strip()
        if not content:
            return ""
        if author and origin:
            return "{}—— {}《{}》".format(content, author, origin)
        if author:
            return "{}—— {}".format(content, author)
        if origin:
            return "{}《{}》".format(content, origin)
        return content
    except Exception:
        return ""


def quote_line():
    """今日名言单行，用于今日概览。"""
    try:
        r, err = _safe_get(QUOTE_API, timeout=10)
        if err or not r:
            return ""
        data = r.json()
        text = data.get("data", {}).get("text", "")
        return text.strip() if text else ""
    except Exception:
        return ""


def index_line():
    """今日指数单行（中文句号分隔）：黄金 x 元/克。比特币 $x USD，用于今日概览。"""
    parts = []
    try:
        r, err = _safe_get(EASTMONEY_GOLD_URL, params={"secid": EASTMONEY_GOLD_SECID, "fields": "f57,f58,f43"}, timeout=10)
        if not err and r and r.status_code == 200:
            data = r.json()
            price_raw = (data.get("data") or {}).get("f43")
            if price_raw is not None:
                parts.append("黄金 {:.2f} 元/克".format(float(price_raw) / 100))
    except Exception:
        pass
    try:
        r, err = _safe_get(COINGECKO_PRICE_URL, params={"ids": "bitcoin", "vs_currencies": "usd"}, timeout=10)
        if not err and r and r.status_code == 200:
            data = r.json()
            btc = data.get("bitcoin", {}).get("usd")
            if btc is not None:
                parts.append("比特币 ${:,.0f} USD".format(btc) if btc >= 1000 else "比特币 ${:,.2f} USD".format(btc))
    except Exception:
        pass
    return "。".join(parts) if parts else ""


def github_trending(language=None, limit=5):
    """Returns (lang_label, list_of_md_lines) or None。用正则解析 GitHub Trending 页面，无 bs4 依赖。"""
    language = language or os.environ.get("GITHUB_TRENDING_LANGUAGE", "java")
    try:
        url = GITHUB_TRENDING_BASE + "/" + language + "?since=daily&spoken_language_code=" if language else GITHUB_TRENDING_BASE + "?since=daily&spoken_language_code="
        r, err = _safe_get(url, timeout=15)
        if err or not r:
            logger.debug("GitHub Trending 获取失败: %s", err or "无响应")
            return None
        # 只匹配 /owner/repo（仅字母数字 _.-），避免匹配到页面其他 href 或 &quot; 等
        pattern = re.compile(r'href="/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)"')
        # 排除导航等非仓库链接（sponsors、trending、explore、topics 等）
        skip_owners = frozenset({"sponsors", "trending", "explore", "topics", "collections", "login", "signup", "features", "enterprise", "blog", "about", "pricing", "contact", "orgs", "settings", "apps"})
        seen = set()
        repos = []
        for m in pattern.finditer(r.text):
            if len(repos) >= limit:
                break
            owner, repo = m.group(1), m.group(2)
            if owner.lower() in skip_owners:
                continue
            path = "/" + owner + "/" + repo
            if path in seen:
                continue
            seen.add(path)
            repos.append({"name": owner + "/" + repo, "url": "https://github.com" + path})
        if not repos:
            return None
        lang_label = (language or "all").capitalize()
        logger.info("GitHub Trending (%s): 获取 %d 条", lang_label, len(repos))
        return lang_label, ["- [{}]({})".format(repo["name"], repo["url"]) for repo in repos]
    except Exception:
        return None


def coding_line():
    """昨日编程单行：花了 X 小时 X 分钟（可选：编辑器占比），用于今日概览。"""
    token = os.environ.get("WAKATIME_TOKEN", "")
    if not token:
        logger.debug("编程时间: 未配置 WAKATIME_TOKEN，跳过")
        return ""
    try:
        yesterday_date = (datetime.now(TZ_SHANGHAI) - timedelta(days=1)).strftime("%Y-%m-%d")
        url = "https://wakatime.com/api/v1/users/current/summaries?api_key={}&start={}&end={}".format(token, yesterday_date, yesterday_date)
        r, err = _safe_get(url, timeout=10)
        if err or not r or r.status_code != 200:
            return ""
        result = r.json()
        total = result.get("cumulative_total", {})
        seconds = total.get("seconds", 0) or 0
        if seconds <= 0:
            logger.info("WakaTime: 昨日无编程记录")
            return "昨天没写代码"
        time_str = (total.get("text") or "").replace("hrs", "小时").replace("hr", "小时").replace("mins", "分钟").replace("min", "分钟").replace("secs", "秒").replace("sec", "秒")
        logger.info("WakaTime: 昨日编程 %s", time_str.strip())
        line = "花了 " + time_str.strip()
        data = result.get("data", [])
        if data:
            editors = data[0].get("editors", [])[:3]
            parts = [x.get("name", "") + " " + str(int(x.get("percent", 0))) + "%" for x in editors if x.get("name") and x.get("percent", 0) > 0]
            if parts:
                line += "。" + "，".join(parts)
        return line
    except Exception:
        return ""


def running_summary():
    """昨日/本月/今年跑步单行（中文逗号分隔），用于今日概览。从本地 data/running.json 的 stats.period_stats 读取。"""
    try:
        local_json = os.path.join(_script_dir, "data", "running.json")
        if not os.path.isfile(local_json):
            logger.debug("跑步距离: 本地 running.json 不存在，跳过")
            return ""
        try:
            with open(local_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("跑步距离: 读取本地 JSON 失败: %s", e)
            return ""
        period = (data.get("stats") or {}).get("period_stats") or {}
        if not period:
            return ""
        def km(p):
            if not p or not isinstance(p, dict):
                return 0.0
            try:
                return float(p.get("total_distance") or 0)
            except (TypeError, ValueError):
                return 0.0
        sum_y = km(period.get("yesterday"))
        sum_m = km(period.get("month"))
        sum_year = km(period.get("year"))
        parts = []
        parts.append("昨天跑了 {:.2f} 公里".format(sum_y) if sum_y > 0 else "昨天没跑")
        parts.append("本月跑了 {:.2f} 公里".format(sum_m) if sum_m > 0 else "本月没跑")
        parts.append("今年跑了 {:.2f} 公里".format(sum_year) if sum_year > 0 else "今年没跑")
        logger.info("跑步: 昨日 %.2f km, 本月 %.2f km, 今年 %.2f km", sum_y, sum_m, sum_year)
        return "；".join(parts)
    except Exception as e:
        logger.warning("跑步距离: 异常 %s", e)
        return ""


# ---------- 4.5 Linkding 昨日书签 ----------
def linkding_yesterday_bookmarks():
    """从 Linkding API 拉取昨日添加的书签。需环境变量 LINKDING_URL、LINKDING_TOKEN。返回 [(title, url), ...]。"""
    base = (os.environ.get("LINKDING_URL") or "https://linkding.chensoul.cc").rstrip("/")
    token = (os.environ.get("LINKDING_TOKEN") or "").strip()
    if not base or not token:
        logger.debug("Linkding: 未配置 LINKDING_URL 或 LINKDING_TOKEN，跳过")
        return []
    logger.info("Linkding: 拉取昨日书签 %s", base)
    url = base + LINKDING_API_BOOKMARKS
    params = {
        "date_filter_by": "added",
        "date_filter_type": "relative",
        "date_filter_relative_string": "yesterday",
        "limit": "100",
    }
    headers = {"Authorization": "Token " + token}
    resp, err = _safe_get(url, params=params, headers=headers, timeout=10)
    if err or not resp:
        logger.warning("Linkding 书签: 请求失败 %s", err or "无响应")
        return []
    try:
        data = resp.json()
    except Exception as e:
        logger.warning("Linkding 书签: JSON 解析失败 %s", e)
        return []
    results = data.get("results") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    out = []
    for b in results:
        if not isinstance(b, dict):
            continue
        link_url = (b.get("url") or "").strip()
        if not link_url:
            continue
        parsed = urlparse(link_url)
        # 仅对 GitHub URL：标题用去域名后的 path
        if parsed.hostname and "github.com" in parsed.hostname.lower():
            path = (parsed.path or "").strip("/")
            title = path if path else (b.get("title") or b.get("website_title") or "").strip() or "无标题"
        else:
            title = (b.get("title") or b.get("website_title") or "").strip() or "无标题"
        if len(title) > LINKDING_TITLE_MAX:
            title = title[: LINKDING_TITLE_MAX - 1] + "…"
        out.append((title, link_url))
    logger.info("Linkding: 昨日书签 %d 条", len(out))
    return out


# ---------- 5. Hacker News ----------
def hn_section():
    try:
        r, err = _safe_get(HN_TOP, timeout=10)
        if err or not r:
            logger.warning("Hacker News 获取失败: %s", err or "无响应")
            return "## 🔥 Hacker News\n\n暂无热门技术资讯"
        ids = r.json()[:30]
        lines = ["## 🔥 Hacker News", ""]
        count = 0
        for sid in ids:
            if count >= HN_MAX_ITEMS:
                break
            r2, err2 = _safe_get(HN_ITEM.format(id=sid), timeout=10)
            if err2 or not r2:
                continue
            story = r2.json() or {}
            title = story.get("title") or "无标题"
            url = story.get("url") or ""
            score = story.get("score") or 0
            if not url or url == "null":
                url = "https://news.ycombinator.com/item?id=" + str(sid)
            if score < HN_MIN_SCORE:
                continue
            count += 1
            lines.append("- [{}]({})".format(title, url))
        if count == 0:
            lines.append("暂无热门技术资讯")
        logger.info("Hacker News: 获取 %d 条", count)
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Hacker News 异常: %s", e)
        return "## 🔥 Hacker News\n\n暂无热门技术资讯"


# ---------- Main ----------
def main():
    logger.info("开始生成每日简报")
    parts = []
    parts.append(header())
    parts.append("")

    # 🗓️ 今日概览（天气、指数、诗词、名言、编程、跑步，中文逗号/句号）
    overview_lines = []
    w = weather_line()
    if w:
        overview_lines.append("- 今日天气。{}".format(w))
    idx_line = index_line()
    if idx_line:
        logger.info("今日指数: %s", idx_line)
        overview_lines.append("- 今日指数。{}".format(idx_line))
    sent_line = poem_line()

    waka_line = coding_line()
    if waka_line:
        overview_lines.append("- 昨日编程。{}".format(waka_line))
    run_line = running_summary()
    if run_line:
        overview_lines.append("- 昨日跑步。{}".format(run_line))
    if overview_lines:
        parts.append("## 📈 今日概览")
        parts.append("")
        parts.extend(overview_lines)
        parts.append("")
        logger.info("今日概览: %d 项", len(overview_lines))

    # 今日任务
    parts.append(tasks_section())
    parts.append("")

    # 昨日收藏（Linkding）
    logger.info("正在拉取昨日收藏 (Linkding)")
    bookmarks = linkding_yesterday_bookmarks()
    if bookmarks:
        parts.append("## 🔖 昨日收藏")
        parts.append("")
        for title, url in bookmarks:
            parts.append("- [{}]({})".format(title, url))
        parts.append("")

    # GitHub Trending
    logger.info("正在拉取 GitHub Trending")
    trend = github_trending(limit=5)
    if trend:
        lang_label, trend_lines = trend
        parts.append("## 📊 GitHub {} Trending".format(lang_label))
        parts.append("")
        parts.append("\n".join(trend_lines))
        parts.append("")

    # Hacker News
    parts.append(hn_section())
    parts.append("")

    # 今日诗词（独立小节）
    if sent_line:
        parts.append("## 📜 今日诗词")
        parts.append("")
        parts.append(sent_line)
        parts.append("")

    parts.append("---")

    quote = quote_line()
    parts.append("✨ Have a great day! " + quote)
    body = "\n".join(parts)
    logger.info("简报生成完成，共 %d 字符", len(body))
    return body


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="生成每日简报（与 send_daily_to_telegram.py 配合发送到 Telegram，支持 GitHub Actions）")
    parser.add_argument("--output", "-o", metavar="FILE", help="写入文件而非 stdout，便于在 GitHub Actions 中传给下一步")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出 DEBUG 级别日志")
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    body = main()
    # 始终保存到 data/daily/YYYY/MM/daily_YYYYMMDD.md
    t = datetime.now(TZ_SHANGHAI)
    daily_subdir = os.path.join(_script_dir, "data", "daily", str(t.year), "{:02d}".format(t.month))
    os.makedirs(daily_subdir, exist_ok=True)
    daily_path = os.path.join(daily_subdir, "daily_{}{:02d}{:02d}.md".format(t.year, t.month, t.day))
    with open(daily_path, "w", encoding="utf-8") as f:
        f.write(body)
    logger.info("简报已保存到 %s", daily_path)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(body)
        logger.info("简报已写入 %s", args.output)
    if not args.output:
        print(body)
    sys.exit(0)
