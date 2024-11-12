import aiohttp
import logging
from typing import Dict, Optional, Tuple
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime
import json

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

            # 创建新会话
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
            }

            # 配置代理
            proxy = self.config.get_proxy_url()
            session = aiohttp.ClientSession(headers=headers, 
                                         timeout=aiohttp.ClientTimeout(total=30),
                                         trust_env=True)
            
            if proxy:
                session._connector._ssl = False
                session.proxy = proxy

            self.sessions[chat_id] = session
            return session

        except Exception as e:
            logging.error(f"创建会话失败: {str(e)}")
            return None

    async def get_session(self, chat_id: int) -> Optional[aiohttp.ClientSession]:
        """获取或创建会话"""
        if chat_id not in self.sessions:
            return await self.create_session(chat_id)
        return self.sessions[chat_id]

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

            # 执行登录
            login_data = {
                'Email': config['forum_username'],
                'Password': config['forum_password']
            }

            async with session.post('https://www.lowendtalk.com/entry/signin', 
                                  data=login_data, 
                                  allow_redirects=True) as response:
                
                if response.status != 200:
                    self.login_attempts[chat_id] = self.login_attempts.get(chat_id, 0) + 1
                    return False, f"登录请求失败: HTTP {response.status}"

                # 验证登录状态
                async with session.get(f"https://www.lowendtalk.com/profile/{config['forum_username']}") as verify_response:
                    if verify_response.status != 200:
                        return False, "验证登录状态失败"

                    html = await verify_response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    if 'sign in' in html.lower():
                        self.login_attempts[chat_id] = self.login_attempts.get(chat_id, 0) + 1
                        return False, "登录验证失败"

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
            session = await self.get_session(chat_id)
            if not session:
                return False

            # 检查最后验证时间
            last = self.last_check.get(chat_id)
            if last and (datetime.now() - last).seconds < 300:  # 5分钟内不重复检查
                return True

            # 验证会话
            async with session.get('https://www.lowendtalk.com/discussions') as response:
                if response.status != 200:
                    return False

                html = await response.text()
                if 'sign in' in html.lower():
                    return False

                self.last_check[chat_id] = datetime.now()
                return True

        except Exception as e:
            logging.error(f"检查会话状态失败: {str(e)}")
            return False

    async def ensure_login(self, chat_id: int) -> bool:
        """确保用户已登录"""
        try:
            # 首先检查现有会话
            if await self.check_session(chat_id):
                return True

            # 尝试使用保存的cookies恢复会话
            cookies = self.db.get_cookies(chat_id)
            if cookies:
                session = await self.create_session(chat_id)
                if session:
                    # 还原cookies
                    for key, cookie_data in cookies.items():
                        session.cookie_jar.update_cookies({
                            'name': key,
                            'value': cookie_data['value'],
                            'domain': cookie_data['domain'],
                            'path': cookie_data['path']
                        })

                    # 验证恢复的会话
                    if await self.check_session(chat_id):
                        return True

            # 如果恢复失败，尝试重新登录
            success, _ = await self.login(chat_id, force=True)
            return success

        except Exception as e:
            logging.error(f"确保登录状态失败: {str(e)}")
            return False

    async def close_session(self, chat_id: int):
        """关闭指定用户的会话"""
        try:
            if chat_id in self.sessions:
                await self.sessions[chat_id].close()
                del self.sessions[chat_id]
        except Exception as e:
            logging.error(f"关闭会话失败: {str(e)}")

    async def close_all_sessions(self):
        """关闭所有会话"""
        for chat_id in list(self.sessions.keys()):
            await self.close_session(chat_id)

    async def get_user_posts(self, chat_id: int, username: str, last_check: Optional[str] = None) -> Tuple[bool, list, str]:
        """获取用户的帖子"""
        try:
            # 确保已登录
            if not await self.ensure_login(chat_id):
                return False, [], "登录状态无效"

            session = self.sessions[chat_id]
            url = f"https://www.lowendtalk.com/profile/{username}/content"

            async with session.get(url) as response:
                if response.status != 200:
                    return False, [], f"获取帖子失败: HTTP {response.status}"

                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                # 检查是否需要重新登录
                if 'sign in' in html.lower():
                    await self.login(chat_id, force=True)
                    return False, [], "需要重新登录"

                posts = []
                for item in soup.find_all('div', class_='Item-Discussion'):
                    try:
                        post_date = item.find('time')['datetime']
                        
                        # 如果有上次检查时间，只获取新帖子
                        if last_check and post_date <= last_check:
                            continue

                        post_data = {
                            'username': username,
                            'title': item.find('a', class_='Title').text.strip(),
                            'date': post_date,
                            'content': item.find('div', class_='Message').text.strip(),
                            'link': "https://www.lowendtalk.com" + item.find('a', class_='Title')['href'],
                            'post_id': item.find('a', class_='Title')['href'].split('/')[-1]
                        }
                        posts.append(post_data)
                    except Exception as e:
                        logging.error(f"解析帖子失败: {str(e)}")
                        continue

                return True, posts, "获取成功"

        except Exception as e:
            logging.error(f"获取用户帖子失败: {str(e)}")
            return False, [], f"获取帖子异常: {str(e)}"

    async def cleanup(self):
        """清理资源"""
        await self.close_all_sessions()
