import csv
import json
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(verbose=True)
wakatime_token = os.environ.get("WAKATIME_TOKEN", "")

def save_history():
    # 读取 JSON 文件
    with open('wakatime.json') as f:
        days = json.load(f)["days"]
        cost_text = result['cumulative_total']['text']
        recent_data = [
            [d["date"], round(d["grand_total"]["total_seconds"]), d["grand_total"]["text"]] for d in days]

    print(recent_data)

    # 将数据写入 CSV 文件
    with open('data/coding.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(recent_data)


def save_yesterday():
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    url = f'https://wakatime.com/api/v1/users/current/summaries?api_key={wakatime_token}&start={yesterday}&end={yesterday}'

    response = requests.get(url)

    if response.status_code == 200:
        result = json.loads(response.text)

        day = result['start']
        cost = round(result['cumulative_total']['seconds'])
        cost_text = result['cumulative_total']['text']

        date = datetime.strptime(
            day, '%Y-%m-%dT%H:%M:%SZ') + timedelta(hours=8)
        normal_date = date.strftime('%Y-%m-%d')

        # 将数据写入 CSV 文件
        with open('data/coding.csv', 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerows([[normal_date, cost, cost_text]])
    else:
        print(response.text)


save_yesterday()
