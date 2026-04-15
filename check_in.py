# coding=UTF-8

import json
import logging
import argparse
import requests
import os
from requests.utils import quote

class CheckIn(object):
    client = requests.Session()
    login_url = "https://w2.v2free.top/auth/login"
    sign_url = "https://w2.v2free.top/user/checkin"

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.masked_username = self.email_masking(username)

    def email_masking(self, email):
        length = len(email)
        at_index = email.rfind('@')
        dot_index = email.rfind('.')
        masked_email = email[0].ljust(at_index, '*') + email[at_index:at_index + 2] + \
            email[dot_index:length].rjust(length - at_index - 2, '*')
        return masked_email

    def check_in(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
            "Referer": "https://w1.v2free.top/auth/login",
        }
        data = {
            "email": self.username,
            "passwd": self.password,
            "code": "",
        }

        # 登录
        login_resp = self.client.post(self.login_url, data=data, headers=headers)
        if login_resp.status_code != 200:
            logging.error(f"登录请求失败，状态码：{login_resp.status_code}")
            return
        if "登录" in login_resp.text or "login" in login_resp.text.lower():
            logging.error(f"登录失败，账号或密码错误。响应片段：{login_resp.text[:200]}")
            return
        logging.info(f"{self.masked_username} 登录成功")

        # 签到
        headers["Referer"] = "https://w1.v2free.top/user"
        sign_resp = self.client.post(self.sign_url, headers=headers)

        # 解析签到结果
        try:
            result = sign_resp.json()
        except requests.exceptions.JSONDecodeError:
            logging.error(f"签到响应非 JSON 格式，状态码：{sign_resp.status_code}，内容：{sign_resp.text[:500]}")
            result = {"msg": "签到失败，响应非 JSON"}

        # 发送通知
        token = os.environ.get("PUSHPLUS_TOKEN", "")
        title = quote(f"{self.masked_username}签到结果")
        content = quote(json.dumps(result, ensure_ascii=False))
        notify_url = f"http://www.pushplus.plus/send?token={token}&title={title}&content={content}"
        requests.get(notify_url)

        logging.info(f"{self.masked_username} 签到结果：{result}")

if __name__ == "__main__":
    LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    parser = argparse.ArgumentParser(description='V2free 自动签到脚本')
    parser.add_argument('--username', type=str, help='您的账号(仅支持单个)')
    parser.add_argument('--password', type=str, help='您的密码(仅支持单个)')
    args = parser.parse_args()
    helper = CheckIn(args.username, args.password)
    helper.check_in()
