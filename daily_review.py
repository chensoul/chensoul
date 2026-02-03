import argparse
import re
import tempfile

import duckdb
import pendulum
import requests
import telebot
from bs4 import BeautifulSoup
from telegramify_markdown import markdownify

GET_UP_MESSAGE_TEMPLATE = """今天是 {date}，今年的第 {day_of_year} 天。{weather_info}

{year_progress}

{today_index}

{coding_info}

{running_info}

💬 每日名言：
{quote}

📜 每日诗词：
{sentence}

{github_trending}

{oschina_news}
"""

TIMEZONE = "Asia/Shanghai"
SENTENCE_API = "https://v2.jinrishici.com/one.json"
QUOTE_API = "https://api.shadiao.pro/du"
OSCHINA_NEWS_URL = "https://www.oschina.net/news"
GITHUB_TRENDING_BASE_URL = "https://github.com/trending"
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
# 国内黄金价格：东方财富 AU9999（上海金交所），单位 元/克
EASTMONEY_GOLD_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_GOLD_SECID = "118.AU9999"

DEFAULT_SENTENCE = """《苦笋》
赏花归去马如飞，
去马如飞酒力微，
酒力微醒时已暮，
醒时已暮赏花归。

—— 宋·苏轼"""

DEFAULT_QUOTE = "生活不是等待暴风雨过去，而是要学会在雨中跳舞。"

# HTTP 请求头常量
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

def _get_yesterday_time():
    """获取昨天的时间对象"""
    return pendulum.now(TIMEZONE).subtract(days=1)


def _safe_request(url, headers=None, params=None, timeout=10, method="get"):
    """安全的 HTTP 请求包装函数"""
    try:
        headers = headers or DEFAULT_HEADERS
        if method.lower() == "get":
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
        else:
            response = requests.post(url, headers=headers, json=params, timeout=timeout)
        response.raise_for_status()
        return response, None
    except requests.exceptions.RequestException as e:
        return None, str(e)


def get_weather_info(city=None, api_key=None):
    """获取天气信息（使用高德地图接口）
    
    Args:
        city: 城市名称（中文），如果为 None，则默认武汉
        api_key: 高德地图 API Key，必需参数
    
    Returns:
        str: 格式化后的天气信息
    """
    if city is None:
        city = "武汉"
    
    try:
        if not api_key:
            print("未设置高德地图 API Key，无法使用高德地图 API")
            return ""
        
        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {
            "key": api_key,
            "city": city,
            "extensions": "all"
        }
        
        response, error = _safe_request(url, params=params, timeout=10)
        if error or not response:
            return ""
        
        data = response.json()
        
        if data.get("status") == "1" and data.get("info") == "OK":
            lives = data.get("lives", [])
            forecasts = data.get("forecasts", [])
            
            if forecasts and forecasts[0].get("casts"):
                casts = forecasts[0]["casts"]
                if casts:
                    today = casts[0]
                    weather_desc = today.get("dayweather", "未知")
                    max_temp = today.get("daytemp", "N/A")
                    min_temp = today.get("nighttemp", "N/A")
                    return f"{city}天气:  {weather_desc} {min_temp}°C ~ {max_temp}°C"
            
            if lives:
                live = lives[0]
                weather_desc = live.get("weather", "未知")
                temp = live.get("temperature", "N/A")
                return f"{city}天气:  {weather_desc} {temp}°C"
        
        return ""
    except Exception as e:
        print(f"高德地图 API 调用失败: {e}")
        return ""


def get_one_sentence():
    """获取今天的一首诗

    使用今日诗词 v2 API 获取完整的诗词内容
    返回格式：《诗名》\n诗词内容\n\n—— 朝代·作者
    """
    try:
        r = requests.get(SENTENCE_API, timeout=10)
        if r.ok:
            data = r.json()

            # 获取诗词来源信息
            origin = data.get("data", {}).get("origin", {})
            title = origin.get("title", "")
            dynasty = origin.get("dynasty", "")
            author = origin.get("author", "")
            content_list = origin.get("content", [])

            if content_list and title and author:
                # 将诗词内容数组合并为字符串（每句一行）
                content = "\n".join(content_list)
                # 格式化输出：《诗名》\n内容\n\n—— 朝代·作者
                poem = f"《{title}》\n{content}\n\n—— {dynasty}·{author}"
                return poem

        return DEFAULT_SENTENCE
    except Exception as e:
        print(f"get SENTENCE_API wrong: {e}")
        return DEFAULT_SENTENCE


def get_daily_quote():
    """获取每日名言（通过API接口）
    
    Returns:
        str: 每日名言
    """
    try:
        response, error = _safe_request(QUOTE_API, timeout=10)
        if error or not response:
            return DEFAULT_QUOTE
        
        data = response.json()
        quote_text = data.get("data", {}).get("text", "")
        
        if quote_text:
            return quote_text
        
        return DEFAULT_QUOTE
    except Exception as e:
        print(f"获取每日名言失败: {e}")
        return DEFAULT_QUOTE

def _get_repo_name_from_url(url):
    """从仓库 URL 中提取仓库名称"""
    return "/".join(url.split("/")[-2:])

def _process_search_items(items, username, item_type):
    """处理搜索结果（PR 或 Issue）"""
    activities = []
    action_text = "创建了 PR" if item_type == "pr" else "创建了 Issue"

    for item in items:
        if item["user"]["login"] == username:
            repo_name = _get_repo_name_from_url(item["repository_url"])
            title = item["title"]
            url = item["html_url"]
            activities.append(f"{action_text}: [{title}]({url}) ({repo_name})")

    return activities

def _process_events(events, yesterday_start, yesterday_end):
    """处理用户事件"""
    activities = []

    for event in events[:100]:
        event_created = pendulum.parse(event["created_at"])

        if event_created < yesterday_start:
            break

        if not (yesterday_start <= event_created <= yesterday_end):
            continue

        if not event.get("public", True):
            continue

        event_type = event["type"]
        repo_name = event["repo"]["name"]

        if event_type == "PullRequestEvent":
            action = event["payload"].get("action")
            if action == "merged":
                pr_data = event["payload"]["pull_request"]
                activities.append(
                    f"合并了 PR: [{pr_data['title']}]({pr_data['html_url']}) ({repo_name})"
                )
        elif event_type == "IssuesEvent":
            action = event["payload"].get("action")
            if action == "closed":
                issue_data = event["payload"]["issue"]
                activities.append(
                    f"关闭了 Issue: [{issue_data['title']}]({issue_data['html_url']}) ({repo_name})"
                )
        elif event_type == "WatchEvent":
            action = event["payload"].get("action")
            if action == "started":
                repo_url = f"https://github.com/{repo_name}"
                activities.append(f"Star 了项目: [{repo_name}]({repo_url})")

    return activities

def get_yesterday_github_activity(github_token=None, username=None):
    """获取昨天的 GitHub 活动"""
    if not username:
        return ""
    try:
        # 时间设置
        yesterday = _get_yesterday_time()
        yesterday_start = yesterday.start_of("day").in_timezone("UTC")
        yesterday_end = yesterday.end_of("day").in_timezone("UTC")
        yesterday_date = yesterday.format("YYYY-MM-DD")

        # 请求头设置
        headers = {}
        if github_token:
            headers.update(
                {
                    "Authorization": f"token {github_token}",
                    "Accept": "application/vnd.github.v3+json",
                }
            )

        activities = []

        # 获取创建的 PR
        search_url = "https://api.github.com/search/issues"
        response, error = _safe_request(
            search_url,
            headers=headers,
            params={
                "q": f"is:pr is:public involves:{username} created:{yesterday_date}",
                "per_page": 100,
            },
        )
        if response:
            pr_data = response.json()
            activities.extend(
                _process_search_items(pr_data.get("items", []), username, "pr")
            )
        elif error:
            print(f"搜索 PR 时出错: {error}")

        # 获取创建的 Issue
        response, error = _safe_request(
            search_url,
            headers=headers,
            params={
                "q": f"is:issue is:public involves:{username} created:{yesterday_date}",
                "per_page": 100,
            },
        )
        if response:
            issue_data = response.json()
            activities.extend(
                _process_search_items(issue_data.get("items", []), username, "issue")
            )
        elif error:
            print(f"搜索 Issue 时出错: {error}")

        # 获取其他事件（合并、关闭、Star 等）
        events_url = f"https://api.github.com/users/{username}/events"
        all_activities = []

        for page in range(1, 4):  # 检查前3页，总共约90个事件
            response, error = _safe_request(
                events_url, headers=headers, params={"page": page, "per_page": 30}
            )

            if error:
                print(f"获取第 {page} 页 Events 时出错: {error}")
                continue

            if not response:
                break  # 没有更多事件了

            events_data = response.json()
            page_activities = _process_events(
                events_data, yesterday_start, yesterday_end
            )
            all_activities.extend(page_activities)

            # 如果这一页事件数少于30，说明已经到底了
            if len(events_data) < 30:
                break

        activities.extend(all_activities)

        # 返回结果
        if activities:
            # 去重并限制数量
            unique_activities = list(dict.fromkeys(activities))
            return "🐙 GitHub：\n" + "\n".join(
                f"• {activity}" for activity in unique_activities[:8]
            )

        return ""

    except Exception as e:
        print(f"Error getting GitHub activity: {e}")
        return ""

def get_yesterday_coding_time(wakatime_token=None):
    """获取昨天的编程时间"""
    if not wakatime_token:
        return ""
    
    try:
        yesterday = _get_yesterday_time()
        yesterday_date = yesterday.format("YYYY-MM-DD")

        url = f'https://wakatime.com/api/v1/users/current/summaries?api_key={wakatime_token}&start={yesterday_date}&end={yesterday_date}'

        response, error = _safe_request(url)
        if error:
            print(f"获取 WakaTime 数据失败: {error}")
            return ""

        if response.status_code == 200:
            result = response.json()
            cumulative_total = result.get('cumulative_total', {})
            cost = round(cumulative_total.get('seconds', 0))
            
            if cost > 0:
                # 格式化时间文本
                cost_text = cumulative_total.get('text', '')
                cost_text = cost_text.replace("hrs", "小时").replace("hr", "小时")
                cost_text = cost_text.replace("mins", "分钟").replace("min", "分钟")
                cost_text = cost_text.replace("secs", "秒").replace("sec", "秒")
                
                lines = [f"⌨️ 编程时间：\n• 昨天写代码花了 {cost_text}"]
                
                # 获取统计信息
                data = result.get('data', [])
                if data and len(data) > 0:
                    day_data = data[0]
                    
                    # 获取编辑器统计信息
                    editors = day_data.get('editors', [])
                    if editors:
                        # 显示前3个编辑器
                        top_editors = editors[:3]
                        editor_texts = []
                        for editor in top_editors:
                            editor_name = editor.get('name', '')
                            editor_percent = editor.get('percent', 0)
                            if editor_name and editor_percent > 0:
                                editor_texts.append(f"{editor_name} {editor_percent:.0f}%")
                        
                        if editor_texts:
                            lines.append(f"• 使用编辑器：{', '.join(editor_texts)}")
                    
                    # 获取语言统计信息
                    languages = day_data.get('languages', [])
                    if languages:
                        # 显示前3个语言
                        top_languages = languages[:3]
                        lang_texts = []
                        for lang in top_languages:
                            lang_name = lang.get('name', '')
                            lang_percent = lang.get('percent', 0)
                            if lang_name and lang_percent > 0:
                                lang_texts.append(f"{lang_name} {lang_percent:.0f}%")
                        
                        if lang_texts:
                            lines.append(f"• 主要语言：{', '.join(lang_texts)}")
                
                return "\n".join(lines)
            else:
                return "⌨️ 编程时间：\n• 昨天没写代码"
        else:
            print(f"获取 WakaTime 数据失败: {response.status_code}")
            return ""
    except Exception as e:
        print(f"Error getting coding time: {e}")
        return ""

def get_running_distance(username=None):
    """获取跑步距离统计"""
    if not username:
        return ""
    
    try:
        url = f"https://github.com/{username}/running_page/raw/refs/heads/master/run_page/data.parquet"
        response, error = _safe_request(url)
        if error or not response.ok:
            return ""

        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(response.content)
            temp_file.flush()

            with duckdb.connect() as conn:
                now = pendulum.now(TIMEZONE)
                yesterday = _get_yesterday_time()
                month_start = now.start_of("month")
                year_start = now.start_of("year")
                tomorrow = now.add(days=1)

                # 构建查询的通用部分
                base_query = """
                SELECT
                    COUNT(*) as count,
                    ROUND(SUM(distance)/1000, 2) as total_km
                FROM read_parquet('{file}')
                WHERE {condition}
                """

                queries = {
                    "yesterday": base_query.format(
                        file=temp_file.name,
                        condition=f"DATE(start_date_local) = '{yesterday.to_date_string()}'"
                    ),
                    "month": base_query.format(
                        file=temp_file.name,
                        condition=f"start_date_local >= '{month_start.to_date_string()}' AND start_date_local < '{tomorrow.to_date_string()}'"
                    ),
                    "year": base_query.format(
                        file=temp_file.name,
                        condition=f"start_date_local >= '{year_start.to_date_string()}' AND start_date_local < '{tomorrow.to_date_string()}'"
                    )
                }

                results = {}
                for key, query in queries.items():
                    result = conn.execute(query).fetchone()
                    results[key] = result

            # 格式化输出
            running_info_parts = []
            period_info = [
                ("yesterday", "昨天", results["yesterday"]),
                ("month", "本月", results["month"]),
                ("year", "今年", results["year"]),
            ]

            for key, label, result in period_info:
                if result and result[0] > 0:
                    running_info_parts.append(f"• {label}跑了 {result[1]} 公里")
                else:
                    running_info_parts.append(f"• {label}没跑")

            return "🏃‍♀️跑步距离：\n" + "\n".join(running_info_parts)

    except Exception as e:
        print(f"Error getting running data: {e}")
        return ""


def get_today_index():
    """获取今日指数：黄金（人民币 元/克，国内接口）和比特币（美元）价格。

    Returns:
        str: 格式化后的今日指数信息
    """
    parts = []

    # 黄金价格（东方财富 AU9999，上海金交所，人民币 元/克）
    try:
        response, error = _safe_request(
            EASTMONEY_GOLD_URL,
            params={
                "secid": EASTMONEY_GOLD_SECID,
                "fields": "f57,f58,f43",  # 代码,名称,最新价(现价)
            },
            timeout=10,
        )
        if not error and response and response.status_code == 200:
            data = response.json()
            inner = data.get("data") or {}
            # f43 为最新价(现价)，单位：分/克，除以 100 得 元/克
            price_raw = inner.get("f43")
            if price_raw is not None:
                price_yuan_per_gram = float(price_raw) / 100
                parts.append(f"• 黄金：{price_yuan_per_gram:,.2f} 元/克")
    except Exception as e:
        print(f"获取黄金价格失败: {e}")

    # 比特币价格（CoinGecko，免费无需 key）
    try:
        response, error = _safe_request(
            COINGECKO_PRICE_URL,
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=10,
        )
        if not error and response and response.status_code == 200:
            data = response.json()
            btc = data.get("bitcoin", {}).get("usd")
            if btc is not None:
                if btc >= 1000:
                    parts.append(f"• 比特币：${btc:,.0f} USD")
                else:
                    parts.append(f"• 比特币：${btc:,.2f} USD")
    except Exception as e:
        print(f"获取比特币价格失败: {e}")

    if not parts:
        return ""

    return "📈 今日指数：\n" + "\n".join(parts)


def get_day_of_year():
    now = pendulum.now(TIMEZONE)
    return now.day_of_year

def get_year_progress():
    """获取今年的进度条"""
    now = pendulum.now(TIMEZONE)
    day_of_year = now.day_of_year

    # 判断是否为闰年
    is_leap_year = now.year % 4 == 0 and (now.year % 100 != 0 or now.year % 400 == 0)
    total_days = 366 if is_leap_year else 365

    # 计算进度百分比
    progress_percent = (day_of_year / total_days) * 100

    # 生成进度条
    progress_bar_width = 20
    filled_blocks = int((day_of_year / total_days) * progress_bar_width)
    empty_blocks = progress_bar_width - filled_blocks

    progress_bar = "█" * filled_blocks + "░" * empty_blocks

    return f"{progress_bar} {progress_percent:.1f}% ({day_of_year}/{total_days})"


def get_oschina_news(limit=5):
    """获取开源中国最新资讯
    
    Args:
        limit: 返回的资讯数量，默认5条
    
    Returns:
        str: 格式化后的资讯文本
    """
    try:
        response, error = _safe_request(OSCHINA_NEWS_URL, timeout=10)
        if error:
            raise Exception(error)
        
        soup = BeautifulSoup(response.text, "html.parser")
        news_list = []
        seen_urls = set()
        
        # 查找所有新闻条目容器（class包含item和news-item）
        news_items = soup.find_all("div", class_=re.compile(r"item.*news-item|news-item.*item"))
        
        for item in news_items:
            if len(news_list) >= limit:
                break
            
            # 从 data-url 属性获取URL
            url = item.get("data-url", "")
            if not url:
                # 尝试从内部链接获取
                link = item.find("a", href=re.compile(r"/news/\d+"))
                if link:
                    url = link.get("href", "")
            
            if not url:
                continue
            
            # 去掉锚点
            url = url.split("#")[0]
            
            # 构建完整URL
            if url.startswith("/"):
                url = f"https://www.oschina.net{url}"
            elif not url.startswith("http"):
                continue
            
            # 去重
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            # 提取标题（从 h3.header .title 或 h3 中）
            title_elem = item.find("h3", class_="header")
            if title_elem:
                title_div = title_elem.find("div", class_="title")
                if title_div:
                    title = title_div.get_text(strip=True)
                else:
                    title = title_elem.get_text(strip=True)
            else:
                title_elem = item.find("h3")
                title = title_elem.get_text(strip=True) if title_elem else ""
            
            if not title or len(title) < 5:
                continue
            
            news_list.append({
                "title": title,
                "url": url
            })
        
        if not news_list:
            return ""
        
        # 格式化资讯
        lines = ["📰 OSChina 最新资讯："]
        for i, news in enumerate(news_list, 1):
            lines.append(f"• [{news['title']}]({news['url']})")
        
        return "\n".join(lines)
        
    except Exception as e:
        print(f"获取 OSChina 资讯失败: {e}")
        return ""


def get_github_trending(language=None, limit=5):
    """获取 GitHub Trending 仓库
    
    Args:
        language: 编程语言，如 'python', 'javascript', 'java' 等，None 表示所有语言
        limit: 返回的仓库数量，默认5个
    
    Returns:
        str: 格式化后的 Trending 信息
    """
    try:
        # 构建 URL
        if language:
            url = f"{GITHUB_TRENDING_BASE_URL}/{language}?since=daily&spoken_language_code="
        else:
            url = f"{GITHUB_TRENDING_BASE_URL}?since=daily&spoken_language_code="
        
        response, error = _safe_request(url, timeout=15)
        if error:
            raise Exception(error)
        
        soup = BeautifulSoup(response.text, "html.parser")
        repos = []
        
        # GitHub Trending 页面的结构：每个仓库在一个 article 标签中
        articles = soup.find_all("article", class_="Box-row")
        
        for article in articles[:limit]:
            # 获取仓库名称和链接
            h2 = article.find("h2", class_="h3")
            if not h2:
                continue
            
            link = h2.find("a")
            if not link:
                continue
            
            repo_name = link.get_text(strip=True)
            repo_url = link.get("href", "")
            if repo_url.startswith("/"):
                repo_url = f"https://github.com{repo_url}"
            
            repos.append({
                "name": repo_name,
                "url": repo_url
            })
        
        if not repos:
            return ""
        
        # 格式化输出
        lines = ["⭐ GitHub Trending For Java："]
        for repo in repos:
            lines.append(f"• [{repo['name']}]({repo['url']})")
        
        return "\n".join(lines)
        
    except Exception as e:
        print(f"获取 GitHub Trending 失败: {e}")
        return ""


def make_get_up_message(github_token, username=None, wakatime_token=None, city=None, trending_language=None, amap_api_key=None):
    try:
        sentence = get_one_sentence()
    except Exception as e:
        print(str(e))
        sentence = DEFAULT_SENTENCE

    try:
        quote = get_daily_quote()
    except Exception as e:
        print(str(e))
        quote = DEFAULT_QUOTE

    now = pendulum.now(TIMEZONE)
    date = now.format("YYYY年MM月DD日")
    day_of_year = get_day_of_year()
    year_progress = get_year_progress()
    weather_info = get_weather_info(city, amap_api_key)
    coding_info = get_yesterday_coding_time(wakatime_token)
    github_activity = get_yesterday_github_activity(github_token, username)
    running_info = get_running_distance(username)
    github_trending = get_github_trending(language=trending_language, limit=5)
    oschina_news = get_oschina_news(limit=5)
    today_index = get_today_index()

    return (
        sentence,
        date,
        day_of_year,
        year_progress,
        weather_info,
        coding_info,
        github_activity,
        running_info,
        github_trending,
        oschina_news,
        quote,
        today_index,
    )


def main(
    github_token,
    username,
    tele_token,
    tele_chat_id,
    wakatime_token=None,
    city="武汉",
    trending_language="java",
    amap_api_key=None,
):
    (
        sentence,
        date,
        day_of_year,
        year_progress,
        weather_info,
        coding_info,
        github_activity,
        running_info,
        github_trending,
        oschina_news,
        quote,
        today_index,
    ) = make_get_up_message(github_token, username, wakatime_token, city, trending_language, amap_api_key)

    body = GET_UP_MESSAGE_TEMPLATE.format(
        date=date,
        sentence=sentence,
        day_of_year=day_of_year,
        year_progress=year_progress,
        weather_info=weather_info,
        coding_info=coding_info,
        github_activity=github_activity,
        running_info=running_info,
        github_trending=github_trending,
        oschina_news=oschina_news,
        quote=quote,
        today_index=today_index,
    )

    print(body)

    if tele_token and tele_chat_id:
        bot = telebot.TeleBot(tele_token)
        try:
            formatted_body = markdownify(body)
            bot.send_message(
                tele_chat_id,
                formatted_body,
                parse_mode="MarkdownV2",
                disable_notification=True,
            )
        except Exception as e:
            print(str(e))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("username", help="GitHub username")
    parser.add_argument("github_token", help="github_token")
    parser.add_argument(
        "--tele_token", help="tele_token", nargs="?", default="", const=""
    )
    parser.add_argument(
        "--tele_chat_id", help="tele_chat_id", nargs="?", default="", const=""
    )
    parser.add_argument(
        "--wakatime_token", help="wakatime_token", nargs="?", default="", const=""
    )
    parser.add_argument(
        "--city", help="城市名称（天气查询，默认：武汉）", nargs="?", default="", const=""
    )
    parser.add_argument(
        "--trending_language", help="GitHub Trending 编程语言（默认：java）", nargs="?", default="", const=""
    )
    parser.add_argument(
        "--amap_api_key", help="高德地图 API Key（天气查询）", nargs="?", default="", const=""
    )
    options = parser.parse_args()
    
    main_kwargs = {
        "github_token": options.github_token,
        "username": options.username,
        "tele_token": options.tele_token,
        "tele_chat_id": options.tele_chat_id,
    }
    
    if options.wakatime_token:
        main_kwargs["wakatime_token"] = options.wakatime_token
    
    if options.city:
        main_kwargs["city"] = options.city
    
    if options.trending_language:
        main_kwargs["trending_language"] = options.trending_language
    
    if options.amap_api_key:
        main_kwargs["amap_api_key"] = options.amap_api_key
    
    main(**main_kwargs)