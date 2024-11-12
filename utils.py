import logging
from typing import Dict, Any, Optional, Union
from datetime import datetime, timezone
import pytz
from pathlib import Path
import asyncio
import functools
import time
import json
import re

class TimeUtils:
    """时间处理工具类"""
    
    @staticmethod
    def format_timestamp(timestamp: Union[str, datetime]) -> str:
        """格式化时间戳为人类可读格式"""
        try:
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                dt = timestamp
                
            # 转换到本地时间
            local_tz = pytz.timezone('Asia/Shanghai')
            local_dt = dt.astimezone(local_tz)
            
            return local_dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logging.error(f"格式化时间戳失败: {str(e)}")
            return str(timestamp)

    @staticmethod
    def get_current_time() -> str:
        """获取当前时间的ISO格式字符串"""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def parse_duration(duration_str: str) -> int:
        """解析持续时间字符串为秒数"""
        units = {
            's': 1,
            'm': 60,
            'h': 3600,
            'd': 86400
        }
        
        match = re.match(r'(\d+)([smhd])', duration_str.lower())
        if match:
            value, unit = match.groups()
            return int(value) * units[unit]
        return 0

class MessageFormatter:
    """消息格式化工具类"""
    
    @staticmethod
    def format_post_message(post_data: Dict[str, Any], preview_length: int = 200) -> str:
        """格式化帖子通知消息"""
        try:
            return (
                f"🔔 新帖子通知\n\n"
                f"👤 用户: {post_data['username']}\n"
                f"📝 标题: {post_data['title']}\n"
                f"⏰ 时间: {TimeUtils.format_timestamp(post_data['date'])}\n"
                f"🔗 链接: {post_data['link']}\n\n"
                f"内容预览:\n{post_data['content'][:preview_length]}..."
            )
        except Exception as e:
            logging.error(f"格式化帖子消息失败: {str(e)}")
            return "消息格式化失败"

    @staticmethod
    def format_error_message(error_type: str, error_message: str) -> str:
        """格式化错误通知消息"""
        return f"❌ 错误通知\n\n类型: {error_type}\n详情: {error_message}"

    @staticmethod
    def format_config_message(config: Dict[str, Any]) -> str:
        """格式化配置信息消息"""
        try:
            return (
                f"📋 当前配置\n\n"
                f"论坛账号: {config['forum_username']}\n"
                f"检查间隔: {config['check_interval']} 秒\n"
                f"代理设置: {'启用' if config.get('proxy', {}).get('enabled') else '禁用'}\n"
                f"加密存储: {'启用' if config.get('security', {}).get('encrypt_credentials') else '禁用'}"
            )
        except Exception as e:
            logging.error(f"格式化配置消息失败: {str(e)}")
            return "配置信息格式化失败"

class RetryDecorator:
    """重试装饰器"""
    
    @staticmethod
    def async_retry(max_retries: int = 3, delay: float = 1.0):
        """异步函数重试装饰器"""
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                last_exception = None
                for attempt in range(max_retries):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        if attempt < max_retries - 1:
                            await asyncio.sleep(delay * (attempt + 1))
                        logging.warning(f"重试 {attempt + 1}/{max_retries}: {str(e)}")
                raise last_exception
            return wrapper
        return decorator

class SafeFileHandler:
    """安全文件处理工具类"""
    
    @staticmethod
    async def safe_write(file_path: Path, content: Union[str, bytes, Dict]):
        """安全地写入文件"""
        temp_path = file_path.with_suffix('.tmp')
        try:
            mode = 'wb' if isinstance(content, bytes) else 'w'
            with open(temp_path, mode) as f:
                if isinstance(content, (str, bytes)):
                    f.write(content)
                else:
                    json.dump(content, f, ensure_ascii=False, indent=4)
            temp_path.replace(file_path)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise e

    @staticmethod
    async def safe_read(file_path: Path, as_json: bool = False) -> Optional[Union[str, Dict]]:
        """安全地读取文件"""
        try:
            with open(file_path, 'r') as f:
                if as_json:
                    return json.load(f)
                return f.read()
        except Exception as e:
            logging.error(f"读取文件失败: {str(e)}")
            return None

class MemoryCache:
    """内存缓存工具类"""
    
    def __init__(self, ttl: int = 300):
        """初始化缓存
        
        Args:
            ttl: 缓存生存时间（秒）
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key in self._cache:
            item = self._cache[key]
            if time.time() < item['expire_at']:
                return item['value']
            del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """设置缓存值"""
        self._cache[key] = {
            'value': value,
            'expire_at': time.time() + (ttl or self._ttl)
        }

    def delete(self, key: str):
        """删除缓存值"""
        self._cache.pop(key, None)

    def clear(self):
        """清空缓存"""
        self._cache.clear()

class RateLimiter:
    """速率限制工具类"""
    
    def __init__(self, max_requests: int, time_window: int):
        """初始化速率限制器
        
        Args:
            max_requests: 时间窗口内的最大请求数
            time_window: 时间窗口大小（秒）
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = {}

    async def acquire(self, key: str) -> bool:
        """获取请求许可"""
        now = time.time()
        
        # 清理过期的请求记录
        if key in self.requests:
            self.requests[key] = [ts for ts in self.requests[key] if now - ts < self.time_window]
        
        # 检查是否超过限制
        if len(self.requests.get(key, [])) >= self.max_requests:
            return False
        
        # 记录新的请求
        if key not in self.requests:
            self.requests[key] = []
        self.requests[key].append(now)
        return True

class Validators:
    """数据验证工具类"""
    
    @staticmethod
    def is_valid_username(username: str) -> bool:
        """验证用户名是否有效"""
        return bool(re.match(r'^[a-zA-Z0-9_-]{3,20}$', username))

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """验证URL是否有效"""
        try:
            pattern = re.compile(
                r'^(?:http|ftp)s?://'  # http:// or https://
                r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
                r'localhost|'  # localhost...
                r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
                r'(?::\d+)?'  # optional port
                r'(?:/?|[/?]\S+)$', re.IGNORECASE)
            return bool(pattern.match(url))
        except Exception:
            return False

    @staticmethod
    def is_valid_interval(interval: int) -> bool:
        """验证时间间隔是否有效"""
        return 60 <= interval <= 86400  # 1分钟到1天

def setup_logger(log_path: Path, log_level: str = 'INFO'):
    """设置日志系统"""
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler()
        ]
    )
    
    # 设置第三方库的日志级别
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
