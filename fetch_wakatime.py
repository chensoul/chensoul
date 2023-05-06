import csv
import json
import os
from datetime import datetime, timedelta

import requests

api_key = os.environ.get("WAKATIME_API_KEY", "")
print(api_key)

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


def save_yesterday():
	today = datetime.now().date()
	yesterday = today - timedelta(days=1)

	url = f'https://wakatime.com/api/v1/users/current/summaries?api_key={api_key}&start={yesterday}&end={yesterday}'

	response = requests.get(url)

	if response.status_code == 200:
		result = json.loads(response.text)

		day = result['start']
		cost = result['cumulative_total']['seconds']
		cost_text = result['cumulative_total']['text'].replace("hrs", "小时").replace("mins", "分钟")

		date = datetime.strptime(day, '%Y-%m-%dT%H:%M:%SZ') + timedelta(hours=8)
		normal_date = date.strftime('%Y-%m-%d')

		if cost > 0:
			china_date_str = date.strftime('%Y年%m月%d日')
			memos_data = {"content": f"{china_date_str}，今天写代码花了 {cost_text} #wakatime"}
			json_data = json.dumps(memos_data)

			requests.post('https://memos.chensoul.com/api/memo?openId=f96cf91e-d692-403d-94ac-94e9347271e2',
						  data=json_data, headers={'Content-Type': 'application/json'})

		# 将数据写入 CSV 文件
		with open('data/wakatime.csv', 'a', newline='') as f:
			writer = csv.writer(f)
			writer.writerows([[normal_date, cost]])
	else:
		print(response.text)


save_yesterday()
