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
from typing import Optional, Tuple, Dict, Any


class CheckIn(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.masked_username = self.email_masking(username)
        self.client = requests.Session()
        self.login_url = "https://w2.v2free.top/auth/login"
        self.sign_url = "https://w2.v2free.top/user/checkin"
        self.user_url = "https://w2.v2free.top/user"
        # 基础头部，后续可动态覆盖
        self.base_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",  # 避免 br 编码问题
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "DNT": "1",
        }
        # 随机 UA 列表
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]

    def email_masking(self, email):
        try:
            at = email.rfind('@')
            dot = email.rfind('.')
            if at == -1 or dot == -1:
                return email
            return email[0].ljust(at, '*') + email[at:at+2] + email[dot:].rjust(len(email)-at-2, '*')
        except:
            return email

    def get_random_user_agent(self) -> str:
        """随机选择一个 User-Agent"""
        return random.choice(self.user_agents)

    def _build_headers(self, extra_headers: Optional[Dict] = None) -> Dict:
        """构建完整的请求头，包含随机 UA 和可选额外头部"""
        headers = self.base_headers.copy()
        headers["User-Agent"] = self.get_random_user_agent()
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _decode_response(self, response: requests.Response) -> str:
        """手动解压 gzip/deflate 响应（requests 通常自动处理，但此处保留原有逻辑）"""
        try:
            if response.headers.get('Content-Encoding') == 'gzip':
                return gzip.GzipFile(fileobj=BytesIO(response.content)).read().decode('utf-8')
            elif response.headers.get('Content-Encoding') == 'deflate':
                return response.content.decode('utf-8', errors='ignore')
            else:
                return response.text
        except:
            return response.text

    def _is_cloudflare_challenge(self, text: str, status_code: int) -> bool:
        """检测是否为 Cloudflare 验证页面"""
        if status_code in (403, 503):
            return True
        if not text:
            return False
        lower_text = text.lower()
        return ('cloudflare' in lower_text or
                'challenge-form' in lower_text or
                'captcha' in lower_text or
                '验证' in text or
                '非机器人' in text)

    def _delay(self, seconds: float):
        """延时，模拟人类行为"""
        time.sleep(seconds)

    def request_with_retry(self, method: str, url: str,
                           max_retries: int = 3,
                           retry_delay: float = 2.0,
                           headers: Optional[Dict] = None,
                           data: Optional[Dict] = None,
                           timeout: int = 15) -> Tuple[Optional[requests.Response], Optional[str]]:
        """
        带重试的请求函数，自动处理 Cloudflare 验证。
        返回 (response, error_msg)，若成功 response 不为 None，否则 error_msg 不为 None。
        """
        for attempt in range(1, max_retries + 1):
            try:
                # 每次重试使用不同的 User-Agent
                req_headers = self._build_headers(headers)
                if method.upper() == 'GET':
                    resp = self.client.get(url, headers=req_headers, timeout=timeout)
                elif method.upper() == 'POST':
                    resp = self.client.post(url, headers=req_headers, data=data, timeout=timeout)
                else:
                    return None, f"不支持的请求方法: {method}"

                # 检查响应内容是否为 Cloudflare 验证页面
                body = self._decode_response(resp)
                if self._is_cloudflare_challenge(body, resp.status_code):
                    logging.warning(f"检测到 Cloudflare 防护 (尝试 {attempt}/{max_retries})")
                    if attempt < max_retries:
                        self._delay(retry_delay * attempt)  # 递增延时
                        continue
                    else:
                        return None, "Cloudflare 验证失败，已达最大重试次数"
                return resp, None

            except requests.RequestException as e:
                logging.warning(f"请求异常 (尝试 {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    self._delay(retry_delay * attempt)
                    continue
                return None, f"请求异常: {e}"
        return None, "未知错误"

    def login(self) -> bool:
        """登录，使用重试机制"""
        data = {"email": self.username, "passwd": self.password, "code": ""}
        extra_headers = {
            "Referer": "https://w2.v2free.top/auth/login",
            "Origin": "https://w2.v2free.top",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        # 登录前随机延时
        self._delay(random.uniform(1, 2))

        resp, err = self.request_with_retry('POST', self.login_url,
                                             headers=extra_headers,
                                             data=data,
                                             max_retries=3,
                                             retry_delay=2.0)
        if err or resp is None:
            logging.error(f"登录请求失败: {err}")
            return False

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
            # 有些情况返回 HTML，检查 cookie 是否设置
            if self.client.cookies.get("uid"):
                logging.info(f"{self.masked_username} 登录成功（cookie 判断）")
                return True
            else:
                logging.error("登录失败，未获取到有效 cookie")
                return False

    def visit_user_page(self):
        """访问用户主页，模拟正常浏览"""
        extra_headers = {"Referer": "https://w2.v2free.top/auth/login"}
        self._delay(random.uniform(0.5, 1.5))
        resp, err = self.request_with_retry('GET', self.user_url,
                                             headers=extra_headers,
                                             max_retries=2,
                                             retry_delay=1.5)
        if err:
            logging.warning(f"访问用户主页失败: {err}")

    def sign(self) -> Dict[str, Any]:
        """签到，使用重试机制"""
        extra_headers = {
            "Referer": "https://w2.v2free.top/user",
            "Origin": "https://w2.v2free.top",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        self._delay(random.uniform(1, 2))

        resp, err = self.request_with_retry('POST', self.sign_url,
                                             headers=extra_headers,
                                             max_retries=3,
                                             retry_delay=2.0)
        if err or resp is None:
            return {"success": False, "msg": f"请求失败: {err}"}

        if resp.status_code != 200:
            return {"success": False, "msg": f"HTTP {resp.status_code}"}

        text = self._decode_response(resp)
        logging.debug(f"签到响应前200字符: {text[:200]}")

        try:
            result = json.loads(text)
            if result.get("ret") == 1:
                return {"success": True, "data": result}
            else:
                return {"success": False, "msg": result.get("msg", "未知错误")}
        except json.JSONDecodeError:
            if self._is_cloudflare_challenge(text, resp.status_code):
                return {"success": False, "msg": "触发 Cloudflare 人机验证，签到失败"}
            return {"success": False, "msg": f"非 JSON 响应: {text[:100]}"}

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
