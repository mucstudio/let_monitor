import sqlite3
from typing import List, Tuple, Optional, Dict, Any
import logging
import json
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

class DatabaseManager:
    def __init__(self, db_path: Path, config_loader):
        """初始化数据库管理器"""
        self.db_path = db_path
        self.config_loader = config_loader
        self.init_database()

    @contextmanager
    def get_connection(self):
        """创建数据库连接的上下文管理器"""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def init_database(self):
        """初始化数据库表"""
        with self.get_connection() as conn:
            # 创建配置表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS configs (
                    chat_id INTEGER PRIMARY KEY,
                    forum_username TEXT,
                    forum_password TEXT,
                    check_interval INTEGER DEFAULT 300,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建监控用户表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS monitored_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    username TEXT,
                    last_check TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(chat_id, username)
                )
            ''')

            # 创建cookies表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_cookies (
                    chat_id INTEGER PRIMARY KEY,
                    cookies TEXT,
                    last_update TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建帖子历史表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS post_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    username TEXT,
                    post_id TEXT,
                    title TEXT,
                    content TEXT,
                    post_date TEXT,
                    link TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(post_id)
                )
            ''')

            conn.commit()

    # 用户配置管理
    def save_user_config(self, chat_id: int, forum_username: str, forum_password: str, 
                        check_interval: Optional[int] = None) -> bool:
        """保存用户配置"""
        try:
            with self.get_connection() as conn:
                # 加密密码
                encrypted_password = self.config_loader.encrypt(forum_password)
                
                if check_interval is None:
                    check_interval = self.config_loader.get_monitoring_config().default_interval

                conn.execute('''
                    INSERT OR REPLACE INTO configs 
                    (chat_id, forum_username, forum_password, check_interval, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (chat_id, forum_username, encrypted_password, check_interval))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"保存用户配置失败: {str(e)}")
            return False

    def get_user_config(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """获取用户配置"""
        try:
            with self.get_connection() as conn:
                result = conn.execute('''
                    SELECT forum_username, forum_password, check_interval
                    FROM configs WHERE chat_id = ?
                ''', (chat_id,)).fetchone()

                if result:
                    username, encrypted_password, interval = result
                    # 解密密码
                    password = self.config_loader.decrypt(encrypted_password)
                    return {
                        'forum_username': username,
                        'forum_password': password,
                        'check_interval': interval
                    }
                return None
        except Exception as e:
            logging.error(f"获取用户配置失败: {str(e)}")
            return None

    # 监控用户管理
    def add_monitored_user(self, chat_id: int, username: str) -> bool:
        """添加监控用户"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO monitored_users (chat_id, username)
                    VALUES (?, ?)
                ''', (chat_id, username))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"添加监控用户失败: {str(e)}")
            return False

    def remove_monitored_user(self, chat_id: int, username: str) -> bool:
        """删除监控用户"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    DELETE FROM monitored_users 
                    WHERE chat_id = ? AND username = ?
                ''', (chat_id, username))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"删除监控用户失败: {str(e)}")
            return False

    def get_monitored_users(self, chat_id: int) -> List[Tuple[str, Optional[str]]]:
        """获取监控用户列表"""
        try:
            with self.get_connection() as conn:
                return conn.execute('''
                    SELECT username, last_check 
                    FROM monitored_users 
                    WHERE chat_id = ?
                ''', (chat_id,)).fetchall()
        except Exception as e:
            logging.error(f"获取监控用户列表失败: {str(e)}")
            return []

    def update_last_check(self, chat_id: int, username: str, last_check: str) -> bool:
        """更新最后检查时间"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    UPDATE monitored_users 
                    SET last_check = ? 
                    WHERE chat_id = ? AND username = ?
                ''', (last_check, chat_id, username))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"更新最后检查时间失败: {str(e)}")
            return False

    # Cookies管理
    def save_cookies(self, chat_id: int, cookies: Dict[str, Any]) -> bool:
        """保存cookies"""
        try:
            with self.get_connection() as conn:
                cookies_json = json.dumps(cookies)
                conn.execute('''
                    INSERT OR REPLACE INTO user_cookies (chat_id, cookies, last_update)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (chat_id, cookies_json))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"保存cookies失败: {str(e)}")
            return False

    def get_cookies(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """获取cookies"""
        try:
            with self.get_connection() as conn:
                result = conn.execute('''
                    SELECT cookies FROM user_cookies WHERE chat_id = ?
                ''', (chat_id,)).fetchone()
                
                if result:
                    return json.loads(result[0])
                return None
        except Exception as e:
            logging.error(f"获取cookies失败: {str(e)}")
            return None

    # 帖子历史管理
    def save_post(self, chat_id: int, post_data: Dict[str, Any]) -> bool:
        """保存帖子记录"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    INSERT OR IGNORE INTO post_history 
                    (chat_id, username, post_id, title, content, post_date, link)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    chat_id, 
                    post_data['username'],
                    post_data['post_id'],
                    post_data['title'],
                    post_data['content'],
                    post_data['post_date'],
                    post_data['link']
                ))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"保存帖子记录失败: {str(e)}")
            return False

    def is_post_exists(self, post_id: str) -> bool:
        """检查帖子是否已存在"""
        try:
            with self.get_connection() as conn:
                result = conn.execute('''
                    SELECT 1 FROM post_history WHERE post_id = ?
                ''', (post_id,)).fetchone()
                return bool(result)
        except Exception as e:
            logging.error(f"检查帖子是否存在失败: {str(e)}")
            return False

    # 数据清理
    def cleanup_old_data(self, days: int = 30) -> bool:
        """清理旧数据"""
        try:
            with self.get_connection() as conn:
                # 清理旧的帖子记录
                conn.execute('''
                    DELETE FROM post_history 
                    WHERE created_at < datetime('now', ?)
                ''', (f'-{days} days',))
                
                # 清理过期的cookies
                conn.execute('''
                    DELETE FROM user_cookies 
                    WHERE last_update < datetime('now', ?)
                ''', (f'-{days} days',))
                
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"清理旧数据失败: {str(e)}")
            return False

    # 数据库备份
    def backup_database(self, backup_path: Optional[Path] = None) -> bool:
        """备份数据库"""
        if backup_path is None:
            backup_path = self.db_path.parent / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            
        try:
            with self.get_connection() as conn:
                backup = sqlite3.connect(backup_path)
                conn.backup(backup)
                backup.close()
                return True
        except Exception as e:
            logging.error(f"备份数据库失败: {str(e)}")
            return False
