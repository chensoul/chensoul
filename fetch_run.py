import requests

# 下载 CSV 文件
url = "https://raw.githubusercontent.com/chensoul/running_page/master/assets/run.csv"
response = requests.get(url)

# 检查响应状态码是否为成功
if response.status_code == 200:
    with open("data/run.csv", "wb") as f:
        f.write(response.content)
        print("文件下载成功！")
else:
    print("文件下载失败。")
