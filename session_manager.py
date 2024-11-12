import aiohttp
import logging
from typing import Dict, Optional, Tuple, List
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime
import json
import time

class SessionManager:
    def __init__(self, database_manager, config_loader):
        """初始化会话管理器"""
        self.db = database_manager
        self.config = config_loader
        self.sessions: Dict[int, aiohttp.ClientSession] = {}
        self.login_attempts: Dict[int, int] = {}
        self.last_check: Dict[int, datetime] = {}

    async def create_session(self, chat_id: int) -> Optional[aiohttp.ClientSession]:
        """创建新的会话"""
        try:
            # 关闭已存在的会话
            if chat_id in self.sessions:
                await self.sessions[chat_id].close()

            # 创建 cookie jar
            jar = aiohttp.CookieJar(unsafe=True)

            # 创建新会话
            connector = aiohttp.TCPConnector(verify_ssl=False)
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                'User-Agent': self.config.config['advanced']['user_agent'],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }

            session = aiohttp.ClientSession(
                headers=headers,
                cookie_jar=jar,
                connector=connector,
                timeout=timeout
            )

            # 配置代理
            proxy = self.config.get_proxy_url()
            if proxy:
                session._connector._ssl = False
                session.proxy = proxy

            self.sessions[chat_id] = session
            return session

        except Exception as e:
            logging.error(f"创建会话失败: {str(e)}")
            return None

    async def login(self, chat_id: int, force: bool = False) -> Tuple[bool, str]:
        """执行登录"""
        try:
            # 检查登录尝试次数
            if not force and self.login_attempts.get(chat_id, 0) >= self.config.config['login']['max_attempts']:
                return False, "登录尝试次数过多，请稍后重试"

            # 获取用户配置
            config = self.db.get_user_config(chat_id)
            if not config:
                return False, "未找到用户配置"

            # 创建新会话
            session = await self.create_session(chat_id)
            if not session:
                return False, "创建会话失败"

            # 首先获取登录页面
            async with session.get('https://www.lowendtalk.com/entry/signin', ssl=False) as response:
                if response.status != 200:
                    return False, f"获取登录页面失败: HTTP {response.status}"
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # 获取 TransientKey
                transient_key = soup.find('input', {'name': 'TransientKey'})
                if not transient_key:
                    return False, "无法获取 TransientKey"
                transient_key = transient_key.get('value', '')

            # 构造登录数据
            login_data = {
                'TransientKey': transient_key,
                'ClientHour': datetime.now().strftime('%H'),
                'ClientMinute': datetime.now().strftime('%M'),
                'ClientTimestamp': str(int(time.time())),
                'Email': config['forum_username'],
                'Password': config['forum_password'],
                'SignIn': 'Sign In'
            }

            # 设置请求头
            headers = {
                'User-Agent': self.config.config['advanced']['user_agent'],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://www.lowendtalk.com',
                'Referer': 'https://www.lowendtalk.com/entry/signin',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            }

            # 执行登录
            async with session.post(
                'https://www.lowendtalk.com/entry/signin',
                data=login_data,
                headers=headers,
                allow_redirects=True,
                ssl=False
            ) as response:
                if response.status not in [200, 302]:
                    self.login_attempts[chat_id] = self.login_attempts.get(chat_id, 0) + 1
                    return False, f"登录请求失败: HTTP {response.status}"
                
                # 验证登录状态
                verify_url = f"https://www.lowendtalk.com/profile/{config['forum_username']}"
                async with session.get(verify_url, ssl=False) as verify_response:
                    if verify_response.status != 200:
                        self.login_attempts[chat_id] = self.login_attempts.get(chat_id, 0) + 1
                        return False, "登录验证失败"

                    verify_html = await verify_response.text()
                    if 'Sign In' in verify_html or 'sign in' in verify_html.lower():
                        self.login_attempts[chat_id] = self.login_attempts.get(chat_id, 0) + 1
                        return False, "登录验证失败，请检查账号密码"

                    # 保存cookies
                    cookies = {
                        cookie.key: {
                            'value': cookie.value,
                            'domain': cookie.get('domain', ''),
                            'path': cookie.get('path', '/'),
                            'expires': cookie.get('expires', ''),
                        }
                        for cookie in session.cookie_jar
                    }
                    self.db.save_cookies(chat_id, cookies)

                    # 重置登录尝试计数
                    self.login_attempts[chat_id] = 0
                    self.last_check[chat_id] = datetime.now()

                    return True, "登录成功"

        except Exception as e:
            logging.error(f"登录过程异常: {str(e)}")
            return False, f"登录异常: {str(e)}"

    async def check_session(self, chat_id: int) -> bool:
        """检查会话是否有效"""
        try:
            if chat_id not in self.sessions:
                return False

            session = self.sessions[chat_id]
            config = self.db.get_user_config(chat_id)
            if not config:
                return False

            # 检查最后验证时间
            last = self.last_check.get(chat_id)
            if last and (datetime.now() - last).total_seconds() < 300:  # 5分钟内不重复检查
                return True

            # 验证会话
            verify_url = f"https://www.lowendtalk.com/profile/{config['forum_username']}"
            async with session.get(verify_url, ssl=False) as response:
                if response.status != 200:
                    return False

                html = await response.text()
                if 'Sign In' in html or 'sign in' in html.lower():
                    return False

                self.last_check[chat_id] = datetime.now()
                return True

        except Exception as e:
            logging.error(f"检查会话状态失败: {str(e)}")
            return False

    async def restore_session(self, chat_id: int) -> bool:
        """使用保存的cookies恢复会话"""
        try:
            cookies = self.db.get_cookies(chat_id)
            if not cookies:
                return False

            session = await self.create_session(chat_id)
            if not session:
                return False

            # 还原cookies
            for key, cookie_data in cookies.items():
                session.cookie_jar.update_cookies({
                    'name': key,
                    'value': cookie_data['value'],
                    'domain': cookie_data.get('domain', ''),
                    'path': cookie_data.get('path', '/')
                })

            # 验证恢复的会话
            if await self.check_session(chat_id):
                return True

            return False

        except Exception as e:
            logging.error(f"恢复会话失败: {str(e)}")
            return False

    async def ensure_login(self, chat_id: int) -> bool:
        """确保用户已登录"""
        try:
            # 检查现有会话
            if await self.check_session(chat_id):
                return True

            # 尝试恢复会话
            if await self.restore_session(chat_id):
                return True

            # 重新登录
            success, _ = await self.login(chat_id, force=True)
            return success

        except Exception as e:
            logging.error(f"确保登录状态失败: {str(e)}")
            return False

    async def get_user_posts(self, chat_id: int, username: str, last_check: Optional[str] = None) -> Tuple[bool, List[Dict], str]:
        """获取用户的帖子"""
        try:
            # 确保已登录
            if not await self.ensure_login(chat_id):
                return False, [], "登录状态无效"

            session = self.sessions[chat_id]
            url = f"https://www.lowendtalk.com/profile/{username}/content"

            async with session.get(url, ssl=False) as response:
                if response.status != 200:
                    return False, [], f"获取帖子失败: HTTP {response.status}"

                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                # 检查是否需要重新登录
                if 'Sign In' in html or 'sign in' in html.lower():
                    if not await self.login(chat_id, force=True):
                        return False, [], "登录失效，重新登录失败"
                    return False, [], "需要重新登录"

                posts = []
                items = soup.find_all('div', class_='ItemDiscussion')
                for item in items:
                    try:
                        time_element = item.find('time')
                        if not time_element:
                            continue
                            
                        post_date = time_element['datetime']
                        
                        # 如果有上次检查时间，只获取新帖子
                        if last_check and post_date <= last_check:
                            continue

                        title_element = item.find('a', class_='Title')
                        if not title_element:
                            continue

                        post_data = {
                            'username': username,
                            'title': title_element.text.strip(),
                            'date': post_date,
                            'content': item.find('div', class_='Message').text.strip() if item.find('div', class_='Message') else '',
                            'link': "https://www.lowendtalk.com" + title_element['href'],
                            'post_id': title_element['href'].split('/')[-1]
                        }
                        posts.append(post_data)

                    except Exception as e:
                        logging.error(f"解析帖子失败: {str(e)}")
                        continue

                return True, posts, "获取成功"

        except Exception as e:
            logging.error(f"获取用户帖子失败: {str(e)}")
            return False, [], f"获取帖子异常: {str(e)}"

    async def close_session(self, chat_id: int):
        """关闭指定用户的会话"""
        try:
            if chat_id in self.sessions:
                await self.sessions[chat_id].close()
                del self.sessions[chat_id]
        except Exception as e:
            logging.error(f"关闭会话失败: {str(e)}")

    async def cleanup(self):
        """清理所有资源"""
        for chat_id in list(self.sessions.keys()):
            await self.close_session(chat_id)
        self.sessions.clear()
        self.login_attempts.clear()
        self.last_check.clear()
