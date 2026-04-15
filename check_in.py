# coding=UTF-8

import json
import logging
import argparse
import sys
import os
import requests


class CheckIn(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.masked_username = self.email_masking(username)
        self.client = requests.Session()
        self.login_url = "https://w2.v2free.top/auth/login"
        self.sign_url = "https://w2.v2free.top/user/checkin"
        self.user_url = "https://w2.v2free.top/user"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def email_masking(self, email):
        """邮箱脱敏显示"""
        try:
            length = len(email)
            at_index = email.rfind('@')
            dot_index = email.rfind('.')
            if at_index == -1 or dot_index == -1:
                return email  # 不是邮箱格式则不处理
            masked = email[0].ljust(at_index, '*') + email[at_index:at_index + 2] + \
                     email[dot_index:length].rjust(length - at_index - 2, '*')
            return masked
        except Exception:
            return email

    def login(self):
        """执行登录，返回是否成功"""
        data = {
            "email": self.username,
            "passwd": self.password,
            "code": "",
        }
        headers = self.headers.copy()
        headers["Referer"] = "https://w2.v2free.top/auth/login"
        headers["Origin"] = "https://w2.v2free.top"

        try:
            resp = self.client.post(self.login_url, data=data, headers=headers, timeout=10)
            logging.debug(f"登录响应状态码: {resp.status_code}")
            logging.debug(f"登录响应内容: {resp.text[:200]}")

            # 检查登录是否成功（根据实际网站返回判断，常见方式：重定向到 /user 或返回包含特定字段）
            if resp.status_code != 200:
                logging.error(f"{self.masked_username} 登录失败，状态码: {resp.status_code}")
                return False

            # 有些网站登录成功后会返回 JSON，包含 ret=1 或 msg="登录成功"
            try:
                json_data = resp.json()
                if json_data.get("ret") == 1 or "成功" in json_data.get("msg", ""):
                    logging.info(f"{self.masked_username} 登录成功")
                    return True
                else:
                    logging.error(f"{self.masked_username} 登录失败: {json_data}")
                    return False
            except json.JSONDecodeError:
                # 如果不是 JSON，则检查是否跳转到用户页面（通过 URL 或 Cookie 判断）
                if "user" in resp.url or self.client.cookies.get("uid"):
                    logging.info(f"{self.masked_username} 登录成功（非 JSON 响应）")
                    return True
                else:
                    logging.error(f"{self.masked_username} 登录失败，响应非 JSON 且未跳转")
                    return False

        except requests.RequestException as e:
            logging.error(f"{self.masked_username} 登录请求异常: {e}")
            return False

    def visit_user_page(self):
        """访问用户主页，刷新 Cookie / 获取必要参数"""
        headers = self.headers.copy()
        headers["Referer"] = "https://w2.v2free.top/auth/login"
        try:
            self.client.get(self.user_url, headers=headers, timeout=10)
        except requests.RequestException as e:
            logging.warning(f"{self.masked_username} 访问用户主页失败: {e}")

    def sign(self):
        """执行签到"""
        headers = self.headers.copy()
        headers["Referer"] = "https://w2.v2free.top/user"
        headers["Origin"] = "https://w2.v2free.top"

        try:
            resp = self.client.post(self.sign_url, headers=headers, timeout=10)
            logging.debug(f"签到响应状态码: {resp.status_code}")
            logging.debug(f"签到响应内容: {resp.text}")

            if resp.status_code != 200:
                return {"success": False, "msg": f"HTTP {resp.status_code}"}

            try:
                result = resp.json()
                return {"success": True, "data": result}
            except json.JSONDecodeError:
                return {"success": False, "msg": resp.text}

        except requests.RequestException as e:
            return {"success": False, "msg": str(e)}

    def send_push(self, title, content):
        """发送 PushPlus 通知"""
        token = os.environ.get("PUSHPLUS_TOKEN", "")
        if not token:
            logging.warning("未配置 PUSHPLUS_TOKEN，跳过推送")
            return

        url = "https://www.pushplus.plus/send"
        params = {
            "token": token,
            "title": title,
            "content": content,
        }
        try:
            requests.get(url, params=params, timeout=5)
        except Exception as e:
            logging.warning(f"推送消息失败: {e}")

    def check_in(self):
        """完整签到流程"""
        logging.info(f"{self.masked_username} 开始执行签到...")

        # 1. 登录
        if not self.login():
            self.send_push(f"{self.masked_username} 签到失败", "登录失败，请检查账号密码或网站状态")
            return False

        # 2. 访问用户主页（模拟点击）
        self.visit_user_page()

        # 3. 签到
        sign_result = self.sign()
        if sign_result["success"]:
            logging.info(f"{self.masked_username} 签到成功: {sign_result['data']}")
            self.send_push(f"{self.masked_username} 签到成功", json.dumps(sign_result['data'], ensure_ascii=False))
            return True
        else:
            logging.error(f"{self.masked_username} 签到失败: {sign_result['msg']}")
            self.send_push(f"{self.masked_username} 签到失败", sign_result['msg'])
            return False


if __name__ == "__main__":
    LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    parser = argparse.ArgumentParser(description='V2free 自动签到脚本')
    parser.add_argument('--username', type=str, required=True, help='您的账号')
    parser.add_argument('--password', type=str, required=True, help='您的密码')
    args = parser.parse_args()

    helper = CheckIn(args.username, args.password)
    success = helper.check_in()

    # 根据结果返回退出码，便于 Actions 判断
    sys.exit(0 if success else 1)
