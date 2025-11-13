import argparse
import os
import tempfile

import duckdb
import pendulum
import requests
import telebot
from dotenv import load_dotenv
from telegramify_markdown import markdownify

load_dotenv(verbose=True)

GET_UP_MESSAGE_TEMPLATE = """今天是 {date}，今年的第 {day_of_year} 天。

{year_progress}

{sentence}

{coding_info}

{running_info}

{github_activity}
"""

SENTENCE_API = "https://v1.jinrishici.com/all"

DEFAULT_SENTENCE = (
    "赏花归去马如飞\r\n去马如飞酒力微\r\n酒力微醒时已暮\r\n醒时已暮赏花归\r\n"
)
DEFAULT_SENTENCE_WITH_INFO = f"{DEFAULT_SENTENCE}\n—— 佚名《回文诗》"
TIMEZONE = "Asia/Shanghai"

def get_one_sentence():
    try:
        r = requests.get(SENTENCE_API)
        if r.ok:
            data = r.json()
            content = data.get("content", "")
            origin = data.get("origin", "")
            author = data.get("author", "")
            
            if content:
                result = content
                if origin or author:
                    info_parts = []
                    if author:
                        info_parts.append(author)
                    if origin:
                        info_parts.append(f"《{origin}》")
                    if info_parts:
                        result += f"\n—— {' '.join(info_parts)}"
                return result
        return DEFAULT_SENTENCE_WITH_INFO
    except Exception:
        print("get SENTENCE_API wrong")
        return DEFAULT_SENTENCE_WITH_INFO

def _get_repo_name_from_url(url):
    """从仓库 URL 中提取仓库名称"""
    return "/".join(url.split("/")[-2:])

def _make_api_request(url, headers, params=None):
    """统一的 API 请求函数"""
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json(), None
        else:
            return None, f"API 请求失败: {response.status_code}"
    except Exception as e:
        return None, f"请求出错: {e}"

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
        yesterday = pendulum.now(TIMEZONE).subtract(days=1)
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
        pr_data, error = _make_api_request(
            search_url,
            headers,
            {
                "q": f"is:pr is:public involves:{username} created:{yesterday_date}",
                "per_page": 100,
            },
        )
        if pr_data:
            activities.extend(
                _process_search_items(pr_data.get("items", []), username, "pr")
            )
        elif error:
            print(f"搜索 PR 时出错: {error}")

        # 获取创建的 Issue
        issue_data, error = _make_api_request(
            search_url,
            headers,
            {
                "q": f"is:issue is:public involves:{username} created:{yesterday_date}",
                "per_page": 100,
            },
        )
        if issue_data:
            activities.extend(
                _process_search_items(issue_data.get("items", []), username, "issue")
            )
        elif error:
            print(f"搜索 Issue 时出错: {error}")

        # 获取其他事件（合并、关闭、Star 等）
        # 检查多页事件，因为 Star 事件可能不在第一页
        events_url = f"https://api.github.com/users/{username}/events"
        all_activities = []

        for page in range(1, 4):  # 检查前3页，总共约90个事件
            page_params = {"page": page, "per_page": 30}
            events_data, error = _make_api_request(events_url, headers, page_params)

            if error:
                print(f"获取第 {page} 页 Events 时出错: {error}")
                continue

            if not events_data:
                break  # 没有更多事件了

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
            return "GitHub：\n" + "\n".join(
                f"• {activity}" for activity in unique_activities[:8]
            )

        return ""

    except Exception as e:
        print(f"Error getting GitHub activity: {e}")
        return ""

def get_yesterday_coding_time(wakatime_token=None):
    """获取昨天的编程时间"""
    try:
        if not wakatime_token:
            return ""

        yesterday = pendulum.now(TIMEZONE).subtract(days=1)
        yesterday_date = yesterday.format("YYYY-MM-DD")

        url = f'https://wakatime.com/api/v1/users/current/summaries?api_key={wakatime_token}&start={yesterday_date}&end={yesterday_date}'

        response = requests.get(url)

        if response.status_code == 200:
            result = response.json()
            cost = round(result['cumulative_total']['seconds'])
            cost_text = result['cumulative_total']['text'].replace(
                "hrs", "小时").replace("mins", "分钟")

            if cost > 0:
                return f"💻编程统计：\n• 昨天写代码花了 {cost_text}"
            else:
                return "💻编程统计：\n• 昨天没写代码"
        else:
            print(f"获取 WakaTime 数据失败: {response.status_code}")
            return ""
    except Exception as e:
        print(f"Error getting coding time: {e}")
        return ""

    return ""

def get_running_distance(username=None):
    try:
        if not username:
            return ""
        url = f"https://github.com/{username}/running_page/raw/refs/heads/master/run_page/data.parquet"
        response = requests.get(url)

        if not response.ok:
            return ""

        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(response.content)
            temp_file.flush()

            with duckdb.connect() as conn:
                now = pendulum.now(TIMEZONE)
                yesterday = now.subtract(days=1)
                month_start = now.start_of("month")
                year_start = now.start_of("year")

                yesterday_query = f"""
                SELECT
                    COUNT(*) as count,
                    ROUND(SUM(distance)/1000, 2) as total_km
                FROM read_parquet('{temp_file.name}')
                WHERE DATE(start_date_local) = '{yesterday.to_date_string()}'
                """

                month_query = f"""
                SELECT
                    COUNT(*) as count,
                    ROUND(SUM(distance)/1000, 2) as total_km
                FROM read_parquet('{temp_file.name}')
                WHERE start_date_local >= '{month_start.to_date_string()}'
                    AND start_date_local < '{now.add(days=1).to_date_string()}'
                """

                year_query = f"""
                SELECT
                    COUNT(*) as count,
                    ROUND(SUM(distance)/1000, 2) as total_km
                FROM read_parquet('{temp_file.name}')
                WHERE start_date_local >= '{year_start.to_date_string()}'
                    AND start_date_local < '{now.add(days=1).to_date_string()}'
                """

                yesterday_result = conn.execute(yesterday_query).fetchone()
                month_result = conn.execute(month_query).fetchone()
                year_result = conn.execute(year_query).fetchone()

            running_info_parts = []

            if yesterday_result and yesterday_result[0] > 0:
                running_info_parts.append(f"• 昨天跑了 {yesterday_result[1]} 公里")
            else:
                running_info_parts.append("• 昨天没跑")

            if month_result and month_result[0] > 0:
                running_info_parts.append(f"• 本月跑了 {month_result[1]} 公里")
            else:
                running_info_parts.append("• 本月没跑")

            if year_result and year_result[0] > 0:
                running_info_parts.append(f"• 今年跑了 {year_result[1]} 公里")
            else:
                running_info_parts.append("• 今年没跑")

            return "🏃‍♀️跑步统计：\n" + "\n".join(running_info_parts)

    except Exception as e:
        print(f"Error getting running data: {e}")
        return ""

    return ""

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

    # 生成进度条 (20个字符宽度)
    progress_bar_width = 20
    filled_blocks = int((day_of_year / total_days) * progress_bar_width)
    empty_blocks = progress_bar_width - filled_blocks

    progress_bar = "█" * filled_blocks + "░" * empty_blocks

    return f"{progress_bar} {progress_percent:.1f}% ({day_of_year}/{total_days})"

def make_get_up_message(github_token, username=None, wakatime_token=None):
    try:
        sentence = get_one_sentence()
        print(f"Sentence: {sentence}")
    except Exception as e:
        print(str(e))
        sentence = DEFAULT_SENTENCE_WITH_INFO

    now = pendulum.now(TIMEZONE)
    date = now.format("YYYY年MM月DD日")
    day_of_year = get_day_of_year()
    year_progress = get_year_progress()
    coding_info = get_yesterday_coding_time(wakatime_token)
    github_activity = get_yesterday_github_activity(github_token, username)
    running_info = get_running_distance(username)

    return (
        sentence,
        date,
        day_of_year,
        year_progress,
        coding_info,
        github_activity,
        running_info,
    )


def main(
    github_token,
    username,
    tele_token,
    tele_chat_id,
    wakatime_token=None,
):
    (
        sentence,
        date,
        day_of_year,
        year_progress,
        coding_info,
        github_activity,
        running_info,
    ) = make_get_up_message(github_token, username, wakatime_token)

    body = GET_UP_MESSAGE_TEMPLATE.format(
        date=date,
        sentence=sentence,
        day_of_year=day_of_year,
        year_progress=year_progress,
        coding_info=coding_info,
        github_activity=github_activity,
        running_info=running_info,
    )

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
    options = parser.parse_args()
    main(
        options.github_token,
        options.username,
        options.tele_token,
        options.tele_chat_id,
        options.wakatime_token if options.wakatime_token else None,
    )