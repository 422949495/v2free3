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
        # 设置超时和延迟
        self.timeout = 60000  # 60秒

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

    def login_and_sign(self) -> Dict[str, Any]:
        """使用 Playwright 登录并签到"""
        result = {"success": False, "data": None, "msg": ""}
        
        with sync_playwright() as p:
            # 启动浏览器（GitHub Actions 环境中使用 chromium）
            # headless=False 可用于本地调试，Actions 中必须 headless=True
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process'
                ]
            )
            context = browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            try:
                # 1. 访问登录页
                logging.info("正在访问登录页面...")
                page.goto(self.login_url, timeout=self.timeout, wait_until='networkidle')
                self._random_delay(1, 2)
                
                # 2. 填写表单
                # 等待邮箱输入框出现
                page.wait_for_selector('input[name="email"]', timeout=self.timeout)
                page.fill('input[name="email"]', self.username)
                page.fill('input[name="passwd"]', self.password)
                self._random_delay(0.5, 1)
                
                # 3. 点击登录按钮
                # 尝试多种选择器
                login_btn = page.locator('button[type="submit"], input[type="submit"], .btn-login, #login-btn')
                if login_btn.count() == 0:
                    # 尝试通过文本定位
                    login_btn = page.locator('text=登录')
                await login_btn.click()
                
                # 等待页面跳转或登录成功标志
                page.wait_for_url(lambda url: '/user' in url or '/dashboard' in url, timeout=self.timeout)
                logging.info("登录成功，页面已跳转")
                
                # 可选：等待 Cloudflare 挑战自动通过（Playwright 会自动执行 JS）
                # 检测是否出现验证页面
                if page.locator('text=验证').count() > 0 or page.locator('text=captcha').count() > 0:
                    logging.warning("检测到验证页面，等待自动通过...")
                    # 等待最多 30 秒让挑战自动完成
                    page.wait_for_function(
                        "() => !document.body.innerText.includes('验证') && !document.body.innerText.includes('captcha')",
                        timeout=30000
                    )
                
                # 4. 访问签到页面
                self._random_delay(1, 2)
                logging.info("正在访问签到页面...")
                page.goto(self.sign_url, timeout=self.timeout, wait_until='networkidle')
                
                # 等待签到响应
                # 签到通常是 POST 请求，但页面可能直接显示结果。我们监听网络响应
                # 方法1：直接检查页面上的提示消息
                # 方法2：拦截 API 响应
                sign_result = None
                
                # 监听签到 API 响应
                def handle_response(response):
                    nonlocal sign_result
                    if '/user/checkin' in response.url and response.status == 200:
                        try:
                            data = response.json()
                            sign_result = data
                        except:
                            pass
                
                page.on('response', handle_response)
                
                # 查找并点击签到按钮（如果存在）
                sign_btn = page.locator('button:has-text("签到"), .btn-checkin, input[value="签到"]')
                if sign_btn.count() > 0:
                    await sign_btn.click()
                    self._random_delay(2, 3)
                
                # 等待 API 响应（最多 10 秒）
                start = time.time()
                while sign_result is None and (time.time() - start) < 10:
                    page.wait_for_timeout(500)
                
                if sign_result:
                    if sign_result.get('ret') == 1:
                        result['success'] = True
                        result['data'] = sign_result
                    else:
                        result['msg'] = sign_result.get('msg', '签到失败')
                else:
                    # 如果抓不到 API，尝试从页面文本提取
                    page_text = page.inner_text('body')
                    if '签到成功' in page_text:
                        result['success'] = True
                        result['msg'] = '签到成功（页面检测）'
                    elif '今日已签到' in page_text or '已经签到过了' in page_text:
                        result['success'] = True
                        result['msg'] = '今日已签到'
                    else:
                        result['msg'] = '未检测到签到结果，可能签到失败或需要手动处理'
                
            except PlaywrightTimeoutError as e:
                logging.error(f"操作超时: {e}")
                result['msg'] = f'页面加载超时: {str(e)}'
            except Exception as e:
                logging.error(f"发生异常: {e}")
                result['msg'] = str(e)
            finally:
                # 截图保存用于调试（可选）
                if not result['success']:
                    try:
                        screenshot = page.screenshot()
                        with open('debug.png', 'wb') as f:
                            f.write(screenshot)
                        logging.info("已保存调试截图 debug.png")
                    except:
                        pass
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
