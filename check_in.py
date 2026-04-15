# coding=UTF-8

import json
import logging
import argparse
import sys
import os
import time
import random
import cloudscraper  # 需要安装 cloudscraper
from typing import Dict, Any


class CheckIn(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.masked_username = self.email_masking(username)
        # 使用 cloudscraper 创建 session，自动处理 Cloudflare 挑战
        self.scraper = cloudscraper.create_scraper(
            interpreter='nodejs',  # 可选 'js2py', 'nodejs'，推荐 nodejs 更快
            delay=10,              # 请求延迟（秒）
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False,
                'custom': None
            }
        )
        self.login_url = "https://w2.v2free.top/auth/login"
        self.sign_url = "https://w2.v2free.top/user/checkin"
        # 移除 user_url，不再访问用户主页

    def email_masking(self, email):
        try:
            at = email.rfind('@')
            dot = email.rfind('.')
            if at == -1 or dot == -1:
                return email
            return email[0].ljust(at, '*') + email[at:at+2] + email[dot:].rjust(len(email)-at-2, '*')
        except:
            return email

    def _delay(self, seconds: float):
        time.sleep(seconds)

    def login(self) -> bool:
        """登录，cloudscraper 会自动处理 Cloudflare 防护"""
        data = {"email": self.username, "passwd": self.password, "code": ""}
        headers = {
            "Referer": "https://w2.v2free.top/auth/login",
            "Origin": "https://w2.v2free.top",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self._delay(random.uniform(1, 2))

        try:
            resp = self.scraper.post(self.login_url, data=data, headers=headers, timeout=30)
            if resp.status_code != 200:
                logging.error(f"登录失败 HTTP {resp.status_code}")
                return False

            try:
                j = resp.json()
                if j.get("ret") == 1 or "成功" in j.get("msg", ""):
                    logging.info(f"{self.masked_username} 登录成功")
                    return True
                else:
                    logging.error(f"登录失败: {j}")
                    return False
            except json.JSONDecodeError:
                # 检查 cookie
                if self.scraper.cookies.get("uid"):
                    logging.info(f"{self.masked_username} 登录成功（cookie 判断）")
                    return True
                else:
                    logging.error("登录失败，未获取到有效 cookie")
                    return False
        except Exception as e:
            logging.error(f"登录异常: {e}")
            return False

    def sign(self) -> Dict[str, Any]:
        """签到，cloudscraper 自动处理 Cloudflare 验证"""
        headers = {
            "Referer": "https://w2.v2free.top/user",
            "Origin": "https://w2.v2free.top",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self._delay(random.uniform(1, 2))

        try:
            resp = self.scraper.post(self.sign_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                return {"success": False, "msg": f"HTTP {resp.status_code}"}

            try:
                result = resp.json()
                if result.get("ret") == 1:
                    return {"success": True, "data": result}
                else:
                    return {"success": False, "msg": result.get("msg", "未知错误")}
            except json.JSONDecodeError:
                # 如果返回的是 HTML 验证页面，说明 Cloudflare 拦截
                if "验证" in resp.text or "captcha" in resp.text.lower():
                    return {"success": False, "msg": "触发人机验证，签到失败"}
                return {"success": False, "msg": f"非 JSON 响应: {resp.text[:100]}"}
        except Exception as e:
            return {"success": False, "msg": str(e)}

    def send_push(self, title, content):
        token = os.environ.get("PUSHPLUS_TOKEN")
        if not token:
            return
        try:
            import requests
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

        # 不再访问用户主页，直接签到
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
