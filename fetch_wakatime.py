import csv
import json
from datetime import datetime, timedelta

import requests


def save_history():
    # 读取 JSON 文件
    with open('wakatime.json') as f:
        days = json.load(f)["days"]
        recent_data = [[d["date"], d["grand_total"]["total_seconds"]] for d in days]

    print(recent_data)

    # 将数据写入 CSV 文件
    with open('data/wakatime.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(recent_data)


api_key = 'waka_0bfc7e4e-fe7a-4eaa-bc4a-3d0cc7d6aac6'


def save_yesterday():
    today = datetime.now().date()
    yesterday = today - timedelta(days=2)

    url = f'https://wakatime.com/api/v1/users/current/summaries?api_key={api_key}&start={yesterday}&end={yesterday}'

    response = requests.get(url)

    if response.status_code == 200:
        result = json.loads(response.text)
        day = result['start']
        cost = result['cumulative_total']['seconds']
        cost_text = result['cumulative_total']['text'].replace("hrs","小时").replace("mins","分钟")

        date = datetime.strptime(day, '%Y-%m-%dT%H:%M:%SZ') + timedelta(hours=8)
        normal_date = date.strftime('%Y-%m-%d')

        if cost > 0:
            china_date_str = date.strftime('%Y年%m月%d日')
            memos_data = {"content": f"{china_date_str}，今天写代码花了 {cost_text}"}
            json_data = json.dumps(memos_data)

            response = requests.post('https://memos.chensoul.com/api/memo?openId=f96cf91e-d692-403d-94ac-94e9347271e2',
                                     data=json_data, headers={'Content-Type': 'application/json'})
            print(response.text)

        # 将数据写入 CSV 文件
        with open('data/wakatime.csv', 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerows([[normal_date, cost]])


save_yesterday()
