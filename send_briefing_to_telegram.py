#!/usr/bin/env python3
"""
将每日简报发送到 Telegram。

用法：
  # 从 stdin 读取简报内容并发送
  python3 generate_briefing.py | python3 send_briefing_to_telegram.py

  # 从文件读取并发送
  python3 generate_briefing.py -o briefing.md
  python3 send_briefing_to_telegram.py -i briefing.md

  # 生成并发送（一步完成）
  python3 send_briefing_to_telegram.py --generate

  # GitHub Actions 中
  - run: python3 generate_briefing.py -o briefing.md
  - run: python3 send_briefing_to_telegram.py -i briefing.md
    env:
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}

  # 仅测试输出（不真正发送）
  python3 send_briefing_to_telegram.py -i briefing.md --dry-run
  python3 send_briefing_to_telegram.py --generate --dry-run

环境变量（默认从同目录 .env 加载）：
  TELEGRAM_BOT_TOKEN  - 必填，Bot 的 token（从 @BotFather 获取）
  TELEGRAM_CHAT_ID    - 必填，目标对话 ID（私聊或群组）
  TELEGRAM_PARSE_MODE - 可选，Markdown | MarkdownV2 | HTML，默认 Markdown；设为空则纯文本
"""

import logging
import os
import re
import sys
import subprocess


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


# 默认加载同目录 .env
_script_dir = os.path.dirname(os.path.abspath(__file__))
_load_env_file(os.path.join(_script_dir, ".env"))

# 日志输出到 stderr，不影响 stdout 管道
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# 可选：telegramify_markdown 可把 Markdown 转成 Telegram 兼容格式，减少解析错误
try:
    from telegramify_markdown import markdownify
    HAS_TELEGRAMIFY = True
except ImportError:
    HAS_TELEGRAMIFY = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def split_for_telegram(text, max_len=TELEGRAM_MAX_MESSAGE_LENGTH):
    """将文本按 Telegram 单条上限分段，尽量在换行处切分。返回分段列表。"""
    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        split_at = text.rfind("\n", 0, max_len + 1)
        if split_at <= 0:
            split_at = max_len
        parts.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return parts


def send_to_telegram(text, bot_token, chat_id, parse_mode="Markdown"):
    """发送消息到 Telegram。超长则按 4096 字符分段发送。parse_mode 为空则发纯文本。"""
    if not HAS_REQUESTS:
        return False, "请安装 requests: pip install requests"
    url = "https://api.telegram.org/bot{}/sendMessage".format(bot_token)
    parts = split_for_telegram(text)
    logger.info("准备发送到 Telegram，共 %d 段，总字符数 %d", len(parts), len(text))
    try:
        for i, chunk in enumerate(parts):
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            logger.debug("发送第 %d/%d 段，长度 %d", i + 1, len(parts), len(chunk))
            r = requests.post(url, json=payload, timeout=30)
            data = r.json()
            if not data.get("ok"):
                logger.error("Telegram API 返回错误: %s", data.get("description", "发送失败"))
                return False, data.get("description", "发送失败")
        logger.info("已成功发送 %d 段到 Telegram", len(parts))
        return True, None
    except Exception as e:
        logger.exception("发送请求异常")
        return False, str(e)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="将每日简报发送到 Telegram")
    parser.add_argument("-i", "--input", metavar="FILE", help="从文件读取简报内容（默认从 stdin）")
    parser.add_argument("--generate", action="store_true", help="先运行 generate_briefing.py 生成简报再发送")
    parser.add_argument("--dry-run", action="store_true", help="仅输出将要发送的内容与分段信息，不调用 Telegram API（无需 TELEGRAM_BOT_TOKEN/CHAT_ID）")
    parser.add_argument("--parse-mode", default=None, help="Telegram parse_mode: Markdown, MarkdownV2, HTML；空为纯文本。默认从 TELEGRAM_PARSE_MODE 读取，否则 Markdown")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出 DEBUG 级别日志")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.generate:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        gen = os.path.join(script_dir, "generate_briefing.py")
        logger.info("正在运行 generate_briefing.py 生成简报")
        try:
            out = subprocess.run(
                [sys.executable, gen],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=script_dir,
                env=os.environ,
            )
            if out.returncode != 0:
                if out.stderr:
                    logger.error("generate_briefing.py stderr: %s", out.stderr.strip())
                logger.error("generate_briefing.py 退出码 %d", out.returncode)
                sys.exit(1)
            text = out.stdout or ""
            logger.info("简报生成完成，长度 %d 字符", len(text.strip()))
        except subprocess.TimeoutExpired:
            logger.error("generate_briefing.py 执行超时")
            sys.exit(1)
        except Exception as e:
            logger.exception("运行 generate_briefing.py 失败: %s", e)
            sys.exit(1)
    elif args.input:
        if not os.path.isfile(args.input):
            logger.error("文件不存在: %s", args.input)
            sys.exit(1)
        with open(args.input, "r", encoding="utf-8") as f:
            text = f.read()
        logger.info("已从文件读取简报: %s，长度 %d 字符", args.input, len(text))
    else:
        text = sys.stdin.read()
        logger.info("已从 stdin 读取简报，长度 %d 字符", len(text))

    text = text.strip()
    if not text:
        logger.error("简报内容为空")
        sys.exit(1)

    parse_mode = args.parse_mode or os.environ.get("TELEGRAM_PARSE_MODE", "Markdown").strip() or None
    if parse_mode and parse_mode.lower() in ("none", "no", "off", "false"):
        parse_mode = None
    logger.debug("parse_mode=%s", parse_mode or "纯文本")

    # 发到 Telegram 时先去掉所有标题前的 # / ##，避免显示为钉子等图标（在 markdownify 之前处理）
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # 若安装 telegramify_markdown 且使用 Markdown，可转为更兼容的格式
    if HAS_TELEGRAMIFY and parse_mode and "markdown" in parse_mode.lower():
        try:
            text = markdownify(text)
            parse_mode = "MarkdownV2"
            logger.info("已使用 telegramify_markdown 转为 MarkdownV2")
        except Exception as e:
            logger.warning("telegramify_markdown 转换失败，使用原格式: %s", e)

    if args.dry_run:
        parts = split_for_telegram(text)
        logger.info("dry-run: 共 %d 段，总字符数 %d", len(parts), len(text))
        for i, chunk in enumerate(parts):
            print("--- 第 {} 段 ({} 字符) ---".format(i + 1, len(chunk)), file=sys.stderr)
            print(chunk)
            if i < len(parts) - 1:
                print(file=sys.stderr)
        return

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        logger.error("请设置环境变量 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID")
        sys.exit(1)

    ok, err = send_to_telegram(text, bot_token, chat_id, parse_mode=parse_mode)
    if not ok:
        logger.error("发送失败: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
