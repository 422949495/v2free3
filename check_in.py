# coding=UTF-8

import os
import sys
import json
import logging
import argparse
import requests
from requests.utils import quote

# ---------- 日志配置 ----------
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

class V2FreeCookieCheckIn:
    SIGN_URL = "https://w2.v2free.top/user/checkin"
    USER_URL  = "https://w2.v2free.top/user"

    def __init__(self, cookie: str):
        self.cookie = cookie.strip()
        self.masked_username = self._extract_and_mask_email(cookie)

    @staticmethod
    def _extract_and_mask_email(cookie: str) -> str:
        """从 Cookie 中提取邮箱并脱敏，用于通知显示"""
        try:
            # 常见存储邮箱的 cookie 键名
            for key in ['email', 'user_email', 'user']:
                if f'{key}=' in cookie:
                    start = cookie.find(f'{key}=') + len(key) + 1
                    end = cookie.find(';', start)
                    if end == -1:
                        end = len(cookie)
                    email = cookie[start:end]
                    # 简单脱敏：保留首字符和 @ 后两位
                    at = email.rfind('@')
                    if at != -1:
                        return email[0] + '******' + email[at:at+2] + '***'
                    else:
                        return email
        except Exception:
            pass
        return "V2Free用户"

    def _send_notification(self, title: str, content: str):
        """通过 PushPlus 发送通知"""
        token = os.environ.get("PUSHPLUS_TOKEN", "")
        if not token:
            logging.warning("未设置 PUSHPLUS_TOKEN，跳过通知")
            return
        url = f"https://www.pushplus.plus/send?token={token}&title={quote(title)}&content={quote(content)}"
        try:
            requests.get(url, timeout=10)
            logging.info("通知发送成功")
        except Exception as e:
            logging.error(f"通知发送失败: {e}")

    def check_in(self) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.USER_URL,
            "Cookie": self.cookie,
        }

        try:
            resp = requests.post(self.SIGN_URL, headers=headers, timeout=15)
            resp.raise_for_status()
            result = resp.json()
        except requests.exceptions.JSONDecodeError:
            # 响应不是 JSON，说明 Cookie 可能已失效或页面返回了错误
            error_msg = f"签到失败：响应非 JSON，状态码 {resp.status_code}。请检查 Cookie 是否有效。"
            logging.error(error_msg)
            result = {"ret": -1, "msg": error_msg}
        except Exception as e:
            logging.exception("签到请求出现异常")
            result = {"ret": -1, "msg": str(e)}

        logging.info(f"{self.masked_username} 签到结果：{result}")
        self._send_notification(
            title=f"{self.masked_username} 签到结果",
            content=json.dumps(result, ensure_ascii=False)
        )
        return result

def main():
    parser = argparse.ArgumentParser(description="V2Free Cookie 签到脚本")
    parser.add_argument("--cookie", type=str, help="完整的登录 Cookie 字符串")
    args = parser.parse_args()

    # 优先从环境变量读取
    cookie = os.environ.get("V2FREE_COOKIE") or args.cookie
    if not cookie:
        logging.error("请设置环境变量 V2FREE_COOKIE 或使用 --cookie 参数")
        sys.exit(1)

    checker = V2FreeCookieCheckIn(cookie)
    result = checker.check_in()

    # 如果签到失败（ret 不为 1），返回非 0 退出码以触发 GitHub Actions 失败通知
    if result.get("ret") != 1:
        sys.exit(1)

if __name__ == "__main__":
    main()
