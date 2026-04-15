# coding=UTF-8

import json
import logging
import argparse
import sys
import os
import time
import random
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from typing import Dict, Any


class CheckIn(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.masked_username = self.email_masking(username)
        self.login_url = "https://w2.v2free.top/auth/login"
        self.sign_url = "https://w2.v2free.top/user/checkin"
        self.timeout = 90000  # 增加到 90 秒

    def email_masking(self, email):
        try:
            at = email.rfind('@')
            dot = email.rfind('.')
            if at == -1 or dot == -1:
                return email
            return email[0].ljust(at, '*') + email[at:at+2] + email[dot:].rjust(len(email)-at-2, '*')
        except:
            return email

    def _random_delay(self, min_sec=0.5, max_sec=1.5):
        time.sleep(random.uniform(min_sec, max_sec))

    def _wait_for_challenge_to_pass(self, page):
        """等待 Cloudflare 挑战自动通过"""
        try:
            # 检测常见的挑战页面特征
            challenge_indicators = [
                "Checking your browser",
                "Just a moment",
                "Enable JavaScript and cookies to continue",
                "DDoS protection",
                "验证",
                "captcha",
                "challenge"
            ]
            # 等待最多 30 秒，每 2 秒检查一次
            for _ in range(15):
                body_text = page.inner_text('body')
                if any(indicator.lower() in body_text.lower() for indicator in challenge_indicators):
                    logging.info("检测到挑战页面，等待自动通过...")
                    page.wait_for_timeout(3000)
                    # 尝试刷新或等待
                    page.reload()
                    continue
                else:
                    # 检查是否有表单元素出现
                    if page.locator('input[name="email"]').count() > 0:
                        return True
                page.wait_for_timeout(2000)
            return False
        except Exception as e:
            logging.warning(f"挑战检测异常: {e}")
            return False

    def login_and_sign(self) -> Dict[str, Any]:
        result = {"success": False, "data": None, "msg": ""}
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-gpu',
                    '--window-size=1280,720'
                ]
            )
            context = browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            try:
                logging.info("正在访问登录页面...")
                # 使用 domcontentloaded 加快加载，然后手动处理挑战
                page.goto(self.login_url, timeout=self.timeout, wait_until='domcontentloaded')
                
                # 等待挑战通过或页面完全加载
                if not self._wait_for_challenge_to_pass(page):
                    # 挑战未通过，尝试直接等待表单出现
                    logging.info("挑战检测未明确，等待表单元素...")
                
                # 再次等待邮箱输入框
                try:
                    page.wait_for_selector('input[name="email"]', timeout=30000)
                except PlaywrightTimeoutError:
                    # 保存当前页面内容用于调试
                    html_content = page.content()
                    with open('debug.html', 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    page.screenshot(path='debug.png')
                    raise Exception("未找到登录表单，可能被 Cloudflare 永久拦截")
                
                logging.info("登录表单已加载，开始填写...")
                self._random_delay(1, 2)
                
                page.fill('input[name="email"]', self.username)
                page.fill('input[name="passwd"]', self.password)
                self._random_delay(0.5, 1)
                
                # 点击登录按钮
                login_btn = page.locator('button[type="submit"], input[type="submit"], .btn-login, #login-btn')
                if login_btn.count() == 0:
                    login_btn = page.locator('text=登录')
                if login_btn.count() == 0:
                    # 尝试通过 text 匹配
                    login_btn = page.locator('button:has-text("登录"), input:has-text("登录")')
                if login_btn.count() == 0:
                    raise Exception("未找到登录按钮")
                login_btn.click()
                
                # 等待跳转
                page.wait_for_url(lambda url: '/user' in url or '/dashboard' in url, timeout=self.timeout)
                logging.info("登录成功，页面已跳转")
                
                # 再次处理可能出现的挑战（登录后可能还有）
                self._wait_for_challenge_to_pass(page)
                
                # 访问签到页面
                self._random_delay(1, 2)
                logging.info("正在访问签到页面...")
                page.goto(self.sign_url, timeout=self.timeout, wait_until='domcontentloaded')
                self._wait_for_challenge_to_pass(page)
                
                # 监听签到 API 响应
                sign_result = None
                def handle_response(response):
                    nonlocal sign_result
                    if '/user/checkin' in response.url and response.status == 200:
                        try:
                            data = response.json()
                            sign_result = data
                        except:
                            pass
                
                page.on('response', handle_response)
                
                # 尝试点击签到按钮
                sign_btn = page.locator('button:has-text("签到"), .btn-checkin, input[value="签到"]')
                if sign_btn.count() > 0:
                    sign_btn.click()
                    self._random_delay(2, 3)
                else:
                    # 如果没有显式按钮，页面可能自动签到，直接等待响应
                    logging.info("未找到签到按钮，等待自动签到响应...")
                
                # 等待 API 响应（最多 15 秒）
                start = time.time()
                while sign_result is None and (time.time() - start) < 15:
                    page.wait_for_timeout(500)
                
                if sign_result:
                    if sign_result.get('ret') == 1:
                        result['success'] = True
                        result['data'] = sign_result
                    else:
                        result['msg'] = sign_result.get('msg', '签到失败')
                else:
                    # 从页面文本提取结果
                    page_text = page.inner_text('body')
                    if '签到成功' in page_text:
                        result['success'] = True
                        result['msg'] = '签到成功（页面检测）'
                    elif '今日已签到' in page_text or '已经签到过了' in page_text:
                        result['success'] = True
                        result['msg'] = '今日已签到'
                    else:
                        # 保存失败时的页面内容
                        with open('sign_failed.html', 'w', encoding='utf-8') as f:
                            f.write(page.content())
                        result['msg'] = '未检测到签到结果，可能签到失败'
                
            except PlaywrightTimeoutError as e:
                logging.error(f"操作超时: {e}")
                result['msg'] = f'页面加载超时: {str(e)}'
                # 保存现场
                try:
                    page.screenshot(path='error_timeout.png')
                    with open('error_timeout.html', 'w', encoding='utf-8') as f:
                        f.write(page.content())
                except:
                    pass
            except Exception as e:
                logging.error(f"发生异常: {e}")
                result['msg'] = str(e)
                try:
                    page.screenshot(path='error_exception.png')
                except:
                    pass
            finally:
                browser.close()
        
        return result

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
        result = self.login_and_sign()
        
        if result['success']:
            logging.info(f"{self.masked_username} ✅ 签到成功: {result.get('data', result.get('msg'))}")
            self.send_push(f"{self.masked_username} 签到成功", json.dumps(result.get('data', {'msg': result.get('msg')}), ensure_ascii=False))
            return True
        else:
            logging.error(f"{self.masked_username} ❌ 签到失败: {result['msg']}")
            self.send_push(f"{self.masked_username} 签到失败", f"原因：{result['msg']}")
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
