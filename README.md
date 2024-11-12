# LowEndTalk 监控机器人

监控 LowEndTalk 论坛用户发帖，并通过 Telegram 发送通知。

## 安装步骤

1. 环境要求:
   - Python 3.8+
   - SQLite3

2. 安装:
```bash
# 克隆项目
git clone https://github.com/yourusername/let_monitor.git
cd let_monitor

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或者在 Windows 上:
# venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

3. 配置:
   - 复制 config.json.example 为 config.json
   - 修改配置文件中的 YOUR_BOT_TOKEN 为你的 Telegram Bot Token
   - 设置其他配置选项

4. 运行:
```bash
python monitor_bot.py
```

5. 设置开机自启:
```bash
# 创建系统服务
sudo nano /etc/systemd/system/let-monitor.service

# 添加以下内容:
[Unit]
Description=LowEndTalk Monitor Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/let_monitor
ExecStart=/path/to/let_monitor/venv/bin/python monitor_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

# 启用服务
sudo systemctl enable let-monitor
sudo systemctl start let-monitor
```

## 使用说明

1. 在 Telegram 中找到你的机器人
2. 发送 /start 开始使用
3. 按照提示设置论坛账号
4. 添加要监控的用户
5. 启动监控

## 常见问题

1. 登录失败：
   - 检查账号密码是否正确
   - 确认网络连接正常
   - 查看日志文件获取详细错误信息

2. 监控未生效：
   - 检查是否正确启动监控
   - 确认设置了正确的检查间隔
   - 查看日志文件排查问题

## 更新日志

v1.0.0 (2024-01-01)
- 初始版本发布
- 支持基本的监控功能
- 自动登录和会话维护

## 维护说明

1. 查看日志:
```bash
tail -f monitor.log
```

2. 重启服务:
```bash
sudo systemctl restart let-monitor
```

3. 更新程序:
```bash
git pull
pip install -r requirements.txt
sudo systemctl restart let-monitor
```
