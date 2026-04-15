# coding=UTF-8

import json
import logging
import argparse
import sys
import os
from curl_cffi import requests

class CheckIn(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.masked_username = self.email_masking(username)
        self.session = requests.Session()
        # 模拟 Chrome 120 的 TLS 指纹
        self.session.impersonate = "chrome120"
        self.login_url = "https://w2.v2free.top/auth/login"
        self.sign_url = "https://w2.v2free.top/user/checkin"
        self.user_url = "https://w2.v2free.top/user"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
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

    def login(self):
        data = {"email": self.username, "passwd": self.password, "code": ""}
        headers = self.headers.copy()
        headers.update({
            "Referer": "https://w2.v2free.top/auth/login",
            "Origin": "https://w2.v2free.top"
        })
        try:
            resp = self.session.post(self.login_url, data=data, headers=headers, timeout=15)
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
            except:
                # 非 JSON 判断 Cookie
                if self.session.cookies.get("uid"):
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
            self.session.get(self.user_url, headers=headers, timeout=10)
        except Exception as e:
            logging.warning(f"访问用户主页失败: {e}")

    def sign(self):
        headers = self.headers.copy()
        headers.update({
            "Referer": "https://w2.v2free.top/user",
            "Origin": "https://w2.v2free.top"
        })
        try:
            resp = self.session.post(self.sign_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return {"success": False, "msg": f"HTTP {resp.status_code}"}

            # 尝试解析 JSON，失败则返回原始文本前 200 字符（但通常是乱码）
            try:
                result = resp.json()
                if result.get("ret") == 1:
                    return {"success": True, "data": result}
                else:
                    return {"success": False, "msg": result.get("msg", "未知错误")}
            except json.JSONDecodeError:
                # 可能是被拦截的 HTML 页面，尝试提取标题或返回提示
                if "验证" in resp.text or "captcha" in resp.text.lower():
                    return {"success": False, "msg": "触发人机验证，签到失败"}
                return {"success": False, "msg": f"非 JSON 响应: {resp.text[:200]}"}

        except Exception as e:
            return {"success": False, "msg": str(e)}

    def send_push(self, title, content):
        token = os.environ.get("PUSHPLUS_TOKEN")
        if not token:
            return
        try:
            # 使用普通 requests 发推送即可
            import requests as req
            req.get("https://www.pushplus.plus/send", params={
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
