#!/usr/bin/env python3
"""
每日简报生成脚本（一体版）。
包含：日期、天气(wttr.in)、今日待办(Memos)、年进度/今日指数/域名/诗词/名言/OSChina/Trending、
GitHub 昨日动态、WakaTime、跑步距离、Hacker News。

今日待办：Memos（MEMOS_API_URL + MEMOS_ACCESS_TOKEN，filter: has_incomplete_tasks == true，
参考 https://usememos.com/docs/usage/shortcuts）；未设置时回退到 BRIEFING_TASKS_SCRIPT 或默认脚本路径。
"""

import logging
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, date, timedelta, timezone
from urllib.request import Request, urlopen

def _load_env_file(path):
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


# 默认加载同目录 .env（BRIEFING_*、MEMOS_*、GITHUB_TOKEN 等）
_script_dir = os.path.dirname(os.path.abspath(__file__))
_load_env_file(os.path.join(_script_dir, ".env"))

# 日志输出到 stderr，不影响 stdout（管道或 -o 文件）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Optional deps
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
try:
    import pendulum
    HAS_PENDULUM = True
except ImportError:
    HAS_PENDULUM = False

# --- 常量 ---
TIMEZONE_NAME = "Asia/Shanghai"
WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
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
OSCHINA_NEWS_URL = "https://www.oschina.net/news"
GITHUB_TRENDING_BASE = "https://github.com/trending"
WHOIS_SERVER_COM = "whois.verisign-grs.com"


def _now():
    if HAS_PENDULUM:
        return pendulum.now(TIMEZONE_NAME)
    return datetime.now()


def _yesterday():
    if HAS_PENDULUM:
        return pendulum.now(TIMEZONE_NAME).subtract(days=1)
    return datetime.now() - timedelta(days=1)


def _safe_get(url, params=None, headers=None, timeout=10):
    if HAS_REQUESTS:
        try:
            h = dict(headers) if headers else {}
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            r.raise_for_status()
            return r, None
        except Exception as e:
            return None, str(e)
    try:
        import urllib.parse
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        req_headers = {"User-Agent": "OpenClaw-DailyBriefing/1.0"}
        if headers:
            req_headers.update(headers)
        req = Request(url, headers=req_headers)
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        class _Resp:
            def __init__(self, text, status_code=200):
                self.text = text
                self.status_code = status_code
                self.content = text.encode("utf-8")
            def json(self):
                import json
                return json.loads(self.text)
        return _Resp(body), None
    except Exception as e:
        return None, str(e)


# ---------- 1. 标题与日期 ----------
def _year_progress_tuple():
    """返回 (pct_str, day, total) 或 None。"""
    try:
        t = _now()
        if HAS_PENDULUM and hasattr(t, "day_of_year"):
            day_of_year, year = t.day_of_year, t.year
        else:
            d = date.today()
            day_of_year = (d - date(d.year, 1, 1)).days + 1
            year = d.year
        is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
        total = 366 if is_leap else 365
        pct = (day_of_year / total) * 100
        return (f"{pct:.1f}%", day_of_year, total)
    except Exception:
        return None


def section_header():
    t = _now()
    if HAS_PENDULUM:
        date_str = t.format("YYYY年MM月DD日")
        wd = WEEKDAY_ZH[t.weekday()]
    else:
        date_str = t.strftime("%Y年%m月%d日")
        wd = WEEKDAY_ZH[t.weekday()]
    yp = _year_progress_tuple()
    if yp:
        pct_str, day, total = yp
        return "# 📅 每日简报 - {}，{}，今年已过去 {} ({}/{})".format(date_str, wd, pct_str, day, total)
    return "# 📅 每日简报 - {}，{}".format(date_str, wd)


# ---------- 2. 天气 (wttr.in) ----------
def _weather_condition_zh(en_val):
    m = {
        "Clear": "晴朗", "Sunny": "晴朗",
        "Partly cloudy": "多云", "Partly Cloudy": "多云",
        "Cloudy": "阴天", "Overcast": "阴沉",
        "Mist": "雾", "Fog": "雾",
        "Light rain": "小雨", "Patchy rain possible": "小雨",
        "Moderate rain": "中雨", "Heavy rain": "大雨",
        "Light snow": "小雪", "Moderate snow": "中雪", "Heavy snow": "大雪",
        "Thundery outbreaks possible": "可能有雷暴",
    }
    return m.get(en_val, en_val)


def _weather_line():
    """返回单行天气内容：Wuhan：多云, 12°C - 21°C（中文逗号）。"""
    city = os.environ.get("BRIEFING_WEATHER_CITY", "Wuhan")
    logger.debug("获取天气: %s", city)
    url = WTTR_URL.format(city=city)
    try:
        r, err = _safe_get(url, timeout=15)
        if err or not r:
            logger.warning("天气获取失败: %s", err or "无响应")
            return None
        data = r.json()
        curr = (data.get("current_condition") or [{}])[0]
        descs = curr.get("weatherDesc") or [{}]
        cond_en = (descs[0].get("value") or "").strip()
        weathers = data.get("weather") or [{}]
        day = weathers[0]
        min_t = day.get("mintempC", "N/A")
        max_t = day.get("maxtempC", "N/A")
        cond = _weather_condition_zh(cond_en)
        return "{}：{}，{}°C - {}°C".format(city, cond, min_t, max_t)
    except Exception as e:
        logger.warning("天气解析失败: %s", e)
        return None


def section_weather():
    """保留：单独天气区块（兼容）。"""
    line = _weather_line()
    if line is None:
        return "## 🌤️ 今日天气\n\n- 天气信息获取失败"
    return "## 🌤️ 今日天气\n\n- {}".format(line)


# ---------- 3. 今日待办：Memos ----------
# Memos: https://github.com/usememos/memos, API: https://usememos.com/docs/api, 筛选: https://usememos.com/docs/usage/shortcuts

def _fetch_memos_tasks():
    """
    从 Memos 拉取含未完成任务的 memo（filter: has_incomplete_tasks == true）。
    解析 content 中的 - [ ] 行作为待办。返回 (success, text) 或 (None, None) 表示未配置。
    """
    base_url = os.environ.get("MEMOS_API_URL", "").strip().rstrip("/")
    token = os.environ.get("MEMOS_ACCESS_TOKEN", "").strip()
    if not base_url or not token:
        return (None, None)
    url = "{}/api/v1/memos".format(base_url)
    params = {"filter": "has_incomplete_tasks == true", "pageSize": 100}
    headers = {"Authorization": "Bearer {}".format(token)}
    r, err = _safe_get(url, params=params, headers=headers, timeout=15)
    if err or not r:
        logger.warning("Memos API 请求失败: %s", err or "无响应")
        return (False, err or "请求失败")
    if r.status_code != 200:
        logger.warning("Memos API 返回 %s", r.status_code)
        return (False, "HTTP {}".format(r.status_code))
    try:
        data = r.json()
    except Exception as e:
        logger.warning("Memos 响应解析失败: %s", e)
        return (False, "解析失败")
    memos = data.get("memos") if isinstance(data, dict) else []
    if not isinstance(memos, list):
        return (True, "")
    # 从每个 memo 的 content 中提取 - [ ] 行（未完成任务）
    task_re = re.compile(r"^\s*-\s*\[\s*\]\s*(.*)$", re.MULTILINE)
    all_tasks = []
    for memo in memos:
        content = (memo.get("content") or "").strip()
        for m in task_re.finditer(content):
            line = m.group(1).strip()
            if line:
                all_tasks.append(line)
    if not all_tasks:
        return (True, "")
    lines = ["- {}".format(t) for t in all_tasks[:20]]
    return (True, "\n".join(lines))


def section_tasks():
    # 优先：Memos（MEMOS_API_URL + MEMOS_ACCESS_TOKEN）
    ok, text = _fetch_memos_tasks()
    if ok is not None:
        if not ok:
            return "## 📋 今日任务\n\n- {}".format(text or "任务获取失败")
        if text and text.strip():
            return "## 📋 今日任务\n\n" + text.strip()
        return "## 📋 今日任务\n\n- 没有待办任务，轻松的一天！"

    # 回退：外部脚本（BRIEFING_TASKS_SCRIPT 或默认路径）
    script = os.environ.get("BRIEFING_TASKS_SCRIPT")
    if not script:
        skill_dir = os.path.expanduser("~/.openclaw/workspace/skills/google-tasks/scripts")
        py_script = os.path.join(skill_dir, "get_tasks.py")
        sh_script = os.path.join(skill_dir, "get_tasks.sh")
        script = py_script if os.path.isfile(py_script) else sh_script
    if not os.path.isfile(script):
        logger.debug("今日任务: 未配置脚本 %s", script)
        return "## 📋 今日任务\n\n- 任务功能未配置"
    logger.debug("今日任务: 执行脚本 %s", script)
    cmd = [sys.executable, script] if script.endswith(".py") else [script]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=os.environ)
        text = (out.stdout or "") + (out.stderr or "")
        if out.returncode != 0 or not text.strip():
            logger.warning("今日任务脚本退出码 %s，输出为空", out.returncode)
            return "## 📋 今日任务\n\n- 任务获取失败"
        if "error" in text.lower() or "failed" in text.lower():
            logger.warning("今日任务脚本返回含 error/failed")
            return "## 📋 今日任务\n\n- 任务获取失败（可能需要重新授权）"
        # 支持脚本输出 "  N. ⬜ 任务" 或 "- [ ] 任务" 或 "- 任务"，统一为 - 任务名 格式（与 briefing.md 一致）
        out_lines = []
        for l in text.strip().splitlines():
            line = l.strip()
            if not line:
                continue
            if line.startswith("- ") and "- [ ]" not in line and "⬜" not in line:
                out_lines.append(line)
            elif "- [ ]" in line:
                out_lines.append("- " + line.split("- [ ]", 1)[-1].strip())
            elif "⬜" in line:
                out_lines.append("- " + line.split("⬜", 1)[-1].strip())
        if not out_lines:
            return "## 📋 今日任务\n\n- 没有待办任务，轻松的一天！"
        task_lines = "\n".join(out_lines[:20])
        return "## 📋 今日任务\n\n{}".format(task_lines)
    except Exception as e:
        logger.warning("今日任务脚本执行异常: %s", e)
        return "## 📋 今日任务\n\n- 任务获取失败"


# ---------- 4. 更多资讯（年进度/指数/域名/诗词/名言/OSChina/Trending/GitHub/WakaTime/跑步）----------
def get_year_progress():
    try:
        t = _now()
        if HAS_PENDULUM and hasattr(t, "day_of_year"):
            day_of_year, year = t.day_of_year, t.year
        else:
            d = date.today()
            day_of_year = (d - date(d.year, 1, 1)).days + 1
            year = d.year
        is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
        total = 366 if is_leap else 365
        pct = (day_of_year / total) * 100
        bar_w = 20
        filled = int((day_of_year / total) * bar_w)
        bar = "█" * filled + "░" * (bar_w - filled)
        return f"{bar} {pct:.1f}% ({day_of_year}/{total})"
    except Exception:
        return ""


def get_one_sentence_line():
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
            return "{}—— {}，《{}》".format(content, author, origin)
        if author:
            return "{}—— {}".format(content, author)
        if origin:
            return "{}《{}》".format(content, origin)
        return content
    except Exception:
        return ""


def get_daily_quote():
    try:
        r, err = _safe_get(QUOTE_API, timeout=10)
        if err or not r:
            return ""
        data = r.json()
        text = data.get("data", {}).get("text", "")
        return text.strip() if text else ""
    except Exception:
        return ""


def get_today_index():
    parts = []
    try:
        r, err = _safe_get(EASTMONEY_GOLD_URL, params={"secid": EASTMONEY_GOLD_SECID, "fields": "f57,f58,f43"}, timeout=10)
        if not err and r and r.status_code == 200:
            data = r.json()
            inner = data.get("data") or {}
            price_raw = inner.get("f43")
            if price_raw is not None:
                parts.append("- 黄金：{:.2f} 元/克".format(float(price_raw) / 100))
    except Exception:
        pass
    try:
        r, err = _safe_get(COINGECKO_PRICE_URL, params={"ids": "bitcoin", "vs_currencies": "usd"}, timeout=10)
        if not err and r and r.status_code == 200:
            data = r.json()
            btc = data.get("bitcoin", {}).get("usd")
            if btc is not None:
                parts.append("- 比特币：${:,.0f} USD".format(btc) if btc >= 1000 else "- 比特币：${:,.2f} USD".format(btc))
    except Exception:
        pass
    if not parts:
        return ""
    return "\n".join(parts)


def get_today_index_line():
    """今日指数单行（中文句号分隔）：黄金：x 元/克。比特币：$x USD"""
    raw = get_today_index()
    if not raw:
        return ""
    parts = [line.strip().lstrip("- ").strip() for line in raw.splitlines() if line.strip()]
    return "。".join(parts) if parts else ""


def _whois_query(domain, timeout=12):
    try:
        tld = domain.split(".")[-1].lower()
        server = WHOIS_SERVER_COM if tld in ("com", "net") else "whois.nic.{}".format(tld)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((server, 43))
        s.send((domain + "\r\n").encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def get_domain_status():
    raw = os.environ.get("BRIEFING_DOMAINS", "")
    domains = [d.strip() for d in raw.split(",") if d.strip()]
    if not domains:
        return ""
    logger.debug("域名状态: 查询 %d 个域名", len(domains))
    lines = []
    for domain in domains:
        text = _whois_query(domain)
        status_str = expiry_str = ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("%") or line.startswith("#"):
                continue
            if "Registry Expiry Date:" in line or "Expiration Date:" in line or "Expiry Date:" in line:
                m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
                if m:
                    expiry_str = m.group(1)
            if "Domain Status:" in line:
                part = line.split("Domain Status:")[-1].strip().split()
                if part:
                    status_str = part[0].rstrip(".")
        if expiry_str or status_str:
            parts = ["- " + domain]
            if status_str:
                parts.append("状态: " + status_str)
            if expiry_str:
                parts.append("过期: " + expiry_str)
            lines.append(" ".join(parts))
        else:
            lines.append("- {}: 查询失败".format(domain))
    if not lines:
        return ""
    return "\n".join(lines)


def get_oschina_news(limit=5):
    if not HAS_REQUESTS or not HAS_BS4:
        return ""
    try:
        r, err = _safe_get(OSCHINA_NEWS_URL, timeout=10)
        if err or not r:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        news_list = []
        seen = set()
        items = soup.find_all("div", class_=re.compile(r"item.*news-item|news-item.*item"))
        for item in items:
            if len(news_list) >= limit:
                break
            url = item.get("data-url", "") or (item.find("a", href=re.compile(r"/news/\d+")) or {}).get("href", "")
            if not url:
                continue
            url = url.split("#")[0]
            if url.startswith("/"):
                url = "https://www.oschina.net" + url
            elif not url.startswith("http"):
                continue
            if url in seen:
                continue
            seen.add(url)
            title_elem = item.find("h3", class_="header") or item.find("h3")
            title = (title_elem.find("div", class_="title") or title_elem).get_text(strip=True) if title_elem else ""
            if not title or len(title) < 5:
                continue
            news_list.append({"title": title, "url": url})
        if not news_list:
            return ""
        return "📰 OSChina 最新资讯：\n" + "\n".join("• [{}]({})".format(n["title"], n["url"]) for n in news_list)
    except Exception:
        return ""


def get_github_trending(language=None, limit=5):
    """Returns (lang_label, list_of_md_lines) or None."""
    if not HAS_REQUESTS or not HAS_BS4:
        return None
    language = language or os.environ.get("GITHUB_TRENDING_LANGUAGE", "java")
    try:
        url = GITHUB_TRENDING_BASE + "/" + language + "?since=daily&spoken_language_code=" if language else GITHUB_TRENDING_BASE + "?since=daily&spoken_language_code="
        r, err = _safe_get(url, timeout=15)
        if err or not r:
            logger.debug("GitHub Trending 获取失败: %s", err or "无响应")
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        repos = []
        for article in soup.find_all("article", class_="Box-row")[:limit]:
            h2 = article.find("h2", class_="h3")
            link = h2.find("a") if h2 else None
            if not link:
                continue
            name = link.get_text(strip=True)
            href = link.get("href", "")
            if href.startswith("/"):
                href = "https://github.com" + href
            repos.append({"name": name, "url": href})
        if not repos:
            return None
        lang_label = (language or "all").capitalize()
        return lang_label, ["- [{}]({})".format(repo["name"], repo["url"]) for repo in repos]
    except Exception:
        return None


def _repo_name_from_url(url):
    return "/".join(url.split("/")[-2:])


def _process_search_items(items, username, item_type):
    action = "创建了 PR" if item_type == "pr" else "创建了 Issue"
    out = []
    for item in items:
        if item.get("user", {}).get("login") != username:
            continue
        repo = _repo_name_from_url(item.get("repository_url", ""))
        out.append("{}: [{}]({}) ({})".format(action, item.get("title", ""), item.get("html_url", ""), repo))
    return out


def _process_events(events, yesterday_start, yesterday_end):
    out = []
    for event in events[:100]:
        created = event.get("created_at")
        if not created:
            continue
        if HAS_PENDULUM:
            event_time = pendulum.parse(created)
        else:
            try:
                event_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception:
                continue
        if HAS_PENDULUM and hasattr(event_time, "in_timezone"):
            event_time = event_time.in_timezone("UTC")
        elif getattr(event_time, "tzinfo", None) is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        if event_time < yesterday_start:
            break
        if not (yesterday_start <= event_time <= yesterday_end):
            continue
        if not event.get("public", True):
            continue
        etype = event.get("type", "")
        repo = event.get("repo", {}).get("name", "")
        if etype == "PullRequestEvent" and event.get("payload", {}).get("action") == "merged":
            pr = event.get("payload", {}).get("pull_request", {})
            out.append("合并了 PR: [{}]({}) ({})".format(pr.get("title", ""), pr.get("html_url", ""), repo))
        elif etype == "IssuesEvent" and event.get("payload", {}).get("action") == "closed":
            issue = event.get("payload", {}).get("issue", {})
            out.append("关闭了 Issue: [{}]({}) ({})".format(issue.get("title", ""), issue.get("html_url", ""), repo))
        elif etype == "WatchEvent" and event.get("payload", {}).get("action") == "started":
            out.append("Star 了项目: [{}](https://github.com/{})".format(repo, repo))
    return out


def get_yesterday_github_activity(username):
    if not username or not HAS_REQUESTS:
        if not username:
            logger.debug("GitHub 昨日动态: 未配置 BRIEFING_GITHUB_USERNAME，跳过")
        return ""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        logger.debug("GitHub 昨日动态: 未配置 GITHUB_TOKEN，跳过")
        return ""
    try:
        if HAS_PENDULUM:
            yesterday = _yesterday()
            yesterday_start = yesterday.start_of("day").in_timezone("UTC")
            yesterday_end = yesterday.end_of("day").in_timezone("UTC")
            yesterday_date = yesterday.format("YYYY-MM-DD")
        else:
            y = _yesterday()
            yesterday_date = y.strftime("%Y-%m-%d")
            yesterday_start = datetime(y.year, y.month, y.day, 0, 0, 0, tzinfo=timezone.utc)
            yesterday_end = datetime(y.year, y.month, y.day, 23, 59, 59, tzinfo=timezone.utc)
        headers = {"Authorization": "token " + token, "Accept": "application/vnd.github.v3+json"}
        activities = []
        search_url = "https://api.github.com/search/issues"
        for q_suffix, item_type in [("is:pr is:public", "pr"), ("is:issue is:public", "issue")]:
            r, err = _safe_get(search_url, params={"q": "involves:{} created:{} {}".format(username, yesterday_date, q_suffix), "per_page": 100}, headers=headers, timeout=15)
            if not err and r and r.status_code == 200:
                activities.extend(_process_search_items(r.json().get("items", []), username, item_type))
        for page in range(1, 4):
            r, err = _safe_get("https://api.github.com/users/{}/events".format(username), params={"page": page, "per_page": 30}, headers=headers, timeout=15)
            if err or not r:
                break
            data = r.json()
            activities.extend(_process_events(data, yesterday_start, yesterday_end))
            if len(data) < 30:
                break
        if not activities:
            return ""
        unique = list(dict.fromkeys(activities))
        return "\n".join("- " + a for a in unique[:8])
    except Exception:
        return ""


def get_yesterday_coding_time():
    token = os.environ.get("WAKATIME_TOKEN", "")
    if not token or not HAS_REQUESTS:
        if not token:
            logger.debug("编程时间: 未配置 WAKATIME_TOKEN，跳过")
        return ""
    try:
        yesterday_date = _yesterday().format("YYYY-MM-DD") if HAS_PENDULUM else _yesterday().strftime("%Y-%m-%d")
        url = "https://wakatime.com/api/v1/users/current/summaries?api_key={}&start={}&end={}".format(token, yesterday_date, yesterday_date)
        r, err = _safe_get(url, timeout=10)
        if err or not r or r.status_code != 200:
            return None
        result = r.json()
        total = result.get("cumulative_total", {})
        seconds = total.get("seconds", 0) or 0
        if seconds <= 0:
            return "- 昨天没写代码"
        text = total.get("text", "").replace("hrs", "小时").replace("hr", "小时").replace("mins", "分钟").replace("min", "分钟").replace("secs", "秒").replace("sec", "秒")
        lines = ["- 昨天写代码花了 " + text]
        data = result.get("data", [])
        if data:
            day = data[0]
            items = day.get("editors", [])[:3]
            parts = [x.get("name", "") + " " + str(int(x.get("percent", 0))) + "%" for x in items if x.get("name") and x.get("percent", 0) > 0]
            if parts:
                lines.append("- 编辑器：" + "，".join(parts))
        return "\n".join(lines)
    except Exception:
        return None


def get_yesterday_coding_time_line():
    """昨日编程单行：花了 X 小时 X 分钟。编辑器明细（用于今日概览）。"""
    raw = get_yesterday_coding_time()
    if not raw:
        return ""
    lines = [line.strip().lstrip("- ").strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""
    first = lines[0].replace("昨天写代码花了 ", "花了 ")
    rest = [l.replace("编辑器：", "").replace(", ", "，") for l in lines[1:]]
    if rest:
        return first + "。" + "，".join(rest)
    return first


def get_running_distance(username):
    if not username or not HAS_REQUESTS:
        if not username:
            logger.debug("跑步距离: 未配置 BRIEFING_GITHUB_USERNAME，跳过")
        return ""
    try:
        import tempfile
        url = "https://github.com/{}/running_page/raw/refs/heads/master/run_page/data.parquet".format(username)
        r, err = _safe_get(url, timeout=15)
        if err or not r:
            return ""
        content = r.content if hasattr(r, "content") else (r.text or "").encode("utf-8")
        try:
            import duckdb
        except ImportError:
            return ""
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name
        try:
            if HAS_PENDULUM:
                now_t = pendulum.now(TIMEZONE_NAME)
                yesterday = _yesterday()
                y_str = yesterday.to_date_string()
                m_start = now_t.start_of("month").to_date_string()
                m_end = now_t.add(days=1).to_date_string()
                y_start = now_t.start_of("year").to_date_string()
            else:
                now_t = datetime.now()
                yesterday = _yesterday()
                y_str = yesterday.strftime("%Y-%m-%d")
                m_start = now_t.replace(day=1).strftime("%Y-%m-%d")
                m_end = (now_t + timedelta(days=1)).strftime("%Y-%m-%d")
                y_start = now_t.replace(month=1, day=1).strftime("%Y-%m-%d")
            conn = duckdb.connect()
            results = {}
            for key, cond in [
                ("yesterday", "DATE(start_date_local) = '" + y_str + "'"),
                ("month", "start_date_local >= '" + m_start + "' AND start_date_local < '" + m_end + "'"),
                ("year", "start_date_local >= '" + y_start + "' AND start_date_local < '" + m_end + "'"),
            ]:
                row = conn.execute("SELECT COUNT(*), ROUND(SUM(distance)/1000, 2) FROM read_parquet('" + path + "') WHERE " + cond).fetchone()
                results[key] = row
            conn.close()
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass
        parts = []
        for label, key in [("昨天", "yesterday"), ("本月", "month"), ("今年", "year")]:
            row = results.get(key)
            if row and row[0] and row[0] > 0:
                parts.append("- {}跑了 {} 公里".format(label, row[1]))
            else:
                parts.append("- {}没跑".format(label))
        return "\n".join(parts)
    except Exception:
        return ""


def get_running_distance_line(username):
    """昨日跑步单行（中文逗号分隔）：昨天跑了 X 公里，本月跑了 X 公里，今年跑了 X 公里。"""
    raw = get_running_distance(username)
    if not raw:
        return ""
    parts = [line.strip().lstrip("- ").strip() for line in raw.splitlines() if line.strip()]
    return "，".join(parts) if parts else ""


def section_github_trending():
    """Returns (title, lines) or None. title is ## 📊 GitHub X Trending."""
    result = get_github_trending(limit=5)
    if not result:
        return None
    lang_label, lines = result
    return "## 📊 GitHub {} Trending".format(lang_label), lines


# ---------- 5. Hacker News ----------
def section_hn():
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
            comments = story.get("descendants") or 0
            if not url or url == "null":
                url = "https://news.ycombinator.com/item?id=" + str(sid)
            if score < HN_MIN_SCORE:
                continue
            count += 1
            lines.append("- [{}]({})".format(title, url))
        if count == 0:
            lines.append("暂无热门技术资讯")
        logger.debug("Hacker News: 获取 %d 条", count)
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Hacker News 异常: %s", e)
        return "## 🔥 Hacker News\n\n暂无热门技术资讯"


# ---------- Main ----------
def main():
    logger.info("开始生成每日简报")
    parts = []
    parts.append(section_header())
    parts.append("")

    # 🗓️ 今日概览（天气、指数、诗词、名言、编程、跑步，中文逗号/句号）
    overview_lines = []
    w = _weather_line()
    if w:
        overview_lines.append("- 今日天气。{}".format(w))
    idx_line = get_today_index_line()
    if idx_line:
        overview_lines.append("- 今日指数。{}".format(idx_line))
    sent_line = get_one_sentence_line()
    if sent_line:
        overview_lines.append("- 今日诗词。{}".format(sent_line))
    quote = get_daily_quote()
    if quote:
        overview_lines.append("- 今日名言。{}".format(quote))
    waka_line = get_yesterday_coding_time_line()
    if waka_line:
        overview_lines.append("- 昨日编程。{}".format(waka_line))
    gh_user = os.environ.get("BRIEFING_GITHUB_USERNAME", "")
    run_line = get_running_distance_line(gh_user)
    if run_line:
        overview_lines.append("- 昨日跑步。{}".format(run_line))
    if overview_lines:
        parts.append("## 📈 今日概览")
        parts.append("")
        parts.extend(overview_lines)
        parts.append("")

    # 今日任务
    parts.append(section_tasks())
    parts.append("")

    # GitHub Trending
    trend = section_github_trending()
    if trend:
        title, trend_lines = trend
        parts.append(title)
        parts.append("")
        parts.append("\n".join(trend_lines))
        parts.append("")

    # Hacker News
    parts.append(section_hn())
    parts.append("")
    parts.append("---")
    parts.append("✨ Have a great day!")
    body = "\n".join(parts)
    logger.info("简报生成完成，共 %d 字符", len(body))
    return body


def _daily_save_path():
    """返回 data/daily/YYYY/MM/daily_YYYYMMDD.md 的绝对路径（基于脚本所在目录）。"""
    t = _now()
    if HAS_PENDULUM:
        year, month, day = t.year, t.month, t.day
    else:
        year, month, day = t.year, t.month, t.day
    subdir = os.path.join(_script_dir, "data", "daily", str(year), "{:02d}".format(month))
    os.makedirs(subdir, exist_ok=True)
    filename = "daily_{}{:02d}{:02d}.md".format(year, month, day)
    return os.path.join(subdir, filename)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="生成每日简报（与 send_briefing_to_telegram.py 配合发送到 Telegram，支持 GitHub Actions）")
    parser.add_argument("--output", "-o", metavar="FILE", help="写入文件而非 stdout，便于在 GitHub Actions 中传给下一步")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出 DEBUG 级别日志")
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    body = main()
    # 始终保存到 data/daily/YYYY/MM/daily_YYYYMMDD.md
    daily_path = _daily_save_path()
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
