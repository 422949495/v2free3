# coding=UTF-8

import json
import logging
import argparse
import sys
import os
import time
import gzip
import random
import requests
from io import BytesIO


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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",  # 禁用 br 避免解压问题
            "Connection": "keep-alive",
        }

    def email_masking(self, email):
        try:
            at = email.rfind('@')
            dot = email.rfind('.')
            if at == -1 or dot == -1:
                return email
            return email[0].ljust(at, '*') + email[at:at+2] + email[dot:].rjust(len(email)-at-2, '*')
        except:
            return email

    def _decode_response(self, response):
        """手动解压响应内容"""
        try:
            if response.headers.get('Content-Encoding') == 'gzip':
                return gzip.GzipFile(fileobj=BytesIO(response.content)).read().decode('utf-8')
            elif response.headers.get('Content-Encoding') == 'deflate':
                return response.content.decode('utf-8', errors='ignore')
            else:
                return response.text
        except:
            return response.text

    def login(self):
        data = {"email": self.username, "passwd": self.password, "code": ""}
        headers = self.headers.copy()
        headers.update({
            "Referer": "https://w2.v2free.top/auth/login",
            "Origin": "https://w2.v2free.top"
        })
        try:
            # 模拟人类点击，稍作延时
            time.sleep(random.uniform(1, 2))
            resp = self.client.post(self.login_url, data=data, headers=headers, timeout=15)
            if resp.status_code != 200:
                logging.error(f"登录失败 HTTP {resp.status_code}")
                return False
            text = self._decode_response(resp)
            logging.debug(f"登录响应前200字符: {text[:200]}")
            try:
                j = json.loads(text)
                if j.get("ret") == 1 or "成功" in j.get("msg", ""):
                    logging.info(f"{self.masked_username} 登录成功")
                    return True
                else:
                    logging.error(f"登录失败: {j}")
                    return False
            except json.JSONDecodeError:
                if self.client.cookies.get("uid"):
                    logging.info(f"{self.masked_username} 登录成功（cookie 判断）")
                    return True
                else:
                    logging.error("登录失败，未获取到有效 cookie")
                    return False
        except Exception as e:
            logging.error(f"登录异常: {e}")
            return False

    def visit_user_page(self):
        headers = self.headers.copy()
        headers["Referer"] = "https://w2.v2free.top/auth/login"
        try:
            time.sleep(random.uniform(0.5, 1.5))
            self.client.get(self.user_url, headers=headers, timeout=10)
        except Exception as e:
            logging.warning(f"访问用户主页失败: {e}")

    def sign(self):
        headers = self.headers.copy()
        headers.update({
            "Referer": "https://w2.v2free.top/user",
            "Origin": "https://w2.v2free.top"
        })
        try:
            time.sleep(random.uniform(1, 2))
            resp = self.client.post(self.sign_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return {"success": False, "msg": f"HTTP {resp.status_code}"}

            text = self._decode_response(resp)
            logging.debug(f"签到响应前200字符: {text[:200]}")

            # 尝试解析 JSON
            try:
                result = json.loads(text)
                if result.get("ret") == 1:
                    return {"success": True, "data": result}
                else:
                    return {"success": False, "msg": result.get("msg", "未知错误")}
            except json.JSONDecodeError:
                # 判断是否触发了验证页面
                if "验证" in text or "captcha" in text.lower() or "非机器人" in text:
                    return {"success": False, "msg": "触发人机验证，签到失败"}
                return {"success": False, "msg": f"非 JSON 响应: {text[:100]}"}

        except Exception as e:
            return {"success": False, "msg": str(e)}

    def send_push(self, title, content):
        token = os.environ.get("PUSHPLUS_TOKEN")
        if not token:
            return
        try:
            requests.get("https://www.pushplus.plus/send", params={
                "token": token,
                "title": title,
                "content": content
            }, timeout=5)
        except:
            pass

    def check_in(self):
        logging.info(f"{self.masked_username} 开始签到...")
        if not self.login():
            self.send_push(f"{self.masked_username} 签到失败", "登录失败")
            return False

        self.visit_user_page()
        sign_result = self.sign()

        if sign_result["success"]:
            logging.info(f"{self.masked_username} ✅ 签到成功: {sign_result['data']}")
            self.send_push(f"{self.masked_username} 签到成功", json.dumps(sign_result['data'], ensure_ascii=False))
            return True
        else:
            logging.error(f"{self.masked_username} ❌ 签到失败: {sign_result['msg']}")
            self.send_push(f"{self.masked_username} 签到失败", f"原因：{sign_result['msg']}")
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', required=True)
    parser.add_argument('--password', required=True)
    args = parser.parse_args()

    helper = CheckIn(args.username, args.password)
    success = helper.check_in()
    sys.exit(0 if success else 1)
