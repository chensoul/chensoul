import csv
import json
import os
import requests
from datetime import datetime, timedelta

# 从同目录 .env 加载（不依赖 python-dotenv）
_script_dir = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(_script_dir, ".env")
if os.path.isfile(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip("'\"")

wakatime_token = os.environ.get("WAKATIME_TOKEN", "")

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
