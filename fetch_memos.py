import requests
import json
import time
import csv
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()
memos_token = os.getenv('MEMOS_TOKEN')

url = f'https://memos.chensoul.cc/api/v1/memos?pageSize=1000&filter=creator=="users/1"'

keyword = '#日记'

# 计算上周一和上周日的日期
today = datetime.now().date()
last_monday = today - timedelta(days=today.weekday(), weeks=1)
last_sunday = last_monday + timedelta(days=6)

# 将日期转换为秒
start_time = int(time.mktime(today.timetuple()))

response = requests.get(url)
print(response.text)


if response.status_code == 200:
    data = json.loads(response.text)

    recent_data = data['memos']
    print(recent_data)

    # recent_data = [d for d in data if start_time <= d['createdTs']]

    with open('data/memos.csv', 'w', newline=''):
        pass

    with open('data/memos.csv', 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['day', 'time', 'url', 'content', 'tags'])

    # 将数据转换为 Markdown 格式，并处理 URL
    for d in recent_data:
        # if keyword in content:
        created_time = datetime.strptime(d['createTime'], "%Y-%m-%dT%H:%M:%SZ")
        date_str = '{}'.format(created_time.strftime('%Y-%m-%d'))
        time_str = '{}'.format(created_time.strftime('%H:%M:%S'))

        content = d['content'].replace(',', '，').replace('**', '')
        tags = d['property']['tags']

        url = 'https://memos.chensoul.cc/m/{} '.format(d['uid'])

        # 将数据写入 CSV 文件
        with open('data/memos.csv', 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerows([[date_str, time_str, url, content, tags]])
else:
    print('请求失败：', response.status_code)
