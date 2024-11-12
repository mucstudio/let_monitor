import json
import os
from typing import Any, Dict, Optional
from pathlib import Path
import logging
from dataclasses import dataclass
from cryptography.fernet import Fernet

@dataclass
class BotConfig:
    token: str
    admin_chat_ids: list
    proxy: Dict[str, Any]

@dataclass
class MonitoringConfig:
    default_interval: int
    min_interval: int
    max_interval: int
    retry_interval: int
    max_retries: int

class ConfigLoader:
    def __init__(self, config_path: str = "config.json"):
        """初始化配置加载器"""
        self.config_path = config_path
        self.config = self.load_config()
        self._encryption_key: Optional[bytes] = None
        self._cipher: Optional[Fernet] = None

    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        self.validate_config(config)
        return config

    def validate_config(self, config: Dict[str, Any]):
        """验证配置文件的必要字段"""
        required_fields = {
            'bot': ['token'],
            'monitoring': ['default_interval', 'min_interval', 'max_interval'],
            'database': ['path'],
            'notification': ['post_preview_length'],
            'login': ['max_attempts', 'auto_relogin'],
            'security': ['encrypt_credentials']
        }

        for section, fields in required_fields.items():
            if section not in config:
                raise ValueError(f"缺少必要的配置部分: {section}")
            
            for field in fields:
                if field not in config[section]:
                    raise ValueError(f"缺少必要的配置字段: {section}.{field}")

    @property
    def cipher(self) -> Fernet:
        """获取或创建加密器"""
        if not self._cipher:
            if self.config['security']['encrypt_credentials']:
                key = self.config['security'].get('encryption_key')
                if not key:
                    key = Fernet.generate_key()
                    self.config['security']['encryption_key'] = key.decode()
                    self.save_config()
                    self._encryption_key = key
                else:
                    self._encryption_key = key.encode()
            else:
                self._encryption_key = Fernet.generate_key()
            
            self._cipher = Fernet(self._encryption_key)
        return self._cipher

    def encrypt(self, data: str) -> str:
        """加密数据"""
        if not self.config['security']['encrypt_credentials']:
            return data
        return self.cipher.encrypt(data.encode()).decode()

    def decrypt(self, data: str) -> str:
        """解密数据"""
        if not self.config['security']['encrypt_credentials']:
            return data
        return self.cipher.decrypt(data.encode()).decode()

    def save_config(self):
        """保存配置到文件"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)

    def get_bot_config(self) -> BotConfig:
        """获取机器人配置"""
        return BotConfig(
            token=self.config['bot']['token'],
            admin_chat_ids=self.config['bot']['admin_chat_ids'],
            proxy=self.config['bot']['proxy']
        )

    def get_monitoring_config(self) -> MonitoringConfig:
        """获取监控配置"""
        return MonitoringConfig(
            default_interval=self.config['monitoring']['default_interval'],
            min_interval=self.config['monitoring']['min_interval'],
            max_interval=self.config['monitoring']['max_interval'],
            retry_interval=self.config['monitoring']['retry_interval'],
            max_retries=self.config['monitoring']['max_retries']
        )

    def get_database_path(self) -> Path:
        """获取数据库路径"""
        return Path(self.config['database']['path'])

    def get_log_config(self) -> Dict[str, Any]:
        """获取日志配置"""
        return {
            'level': self.config['advanced']['log_level'],
            'filename': self.config['advanced']['log_file'],
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        }

    def get_request_timeout(self) -> int:
        """获取请求超时时间"""
        return self.config['advanced']['request_timeout']

    def get_post_preview_length(self) -> int:
        """获取帖子预览长度"""
        return self.config['notification']['post_preview_length']

    def is_user_allowed(self, user_id: int) -> bool:
        """检查用户是否被允许使用机器人"""
        allowed_users = self.config['security']['allowed_users']
        return not allowed_users or user_id in allowed_users

    def get_proxy_url(self) -> Optional[str]:
        """获取代理URL"""
        proxy_config = self.config['bot']['proxy']
        return proxy_config['url'] if proxy_config['enabled'] else None

def setup_logging(config: Dict[str, Any]):
    """设置日志"""
    logging.basicConfig(
        level=getattr(logging, config['level']),
        filename=config['filename'],
        format=config['format'],
        handlers=[
            logging.FileHandler(config['filename']),
            logging.StreamHandler()  # 同时输出到控制台
        ]
    )
    # 设置第三方库的日志级别
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
