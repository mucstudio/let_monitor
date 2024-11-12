import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path

from config_loader import ConfigLoader, setup_logging
from database import DatabaseManager
from session_manager import SessionManager
from utils import TimeUtils, MessageFormatter, RetryDecorator, Validators

# 状态定义
(WAITING_USERNAME, WAITING_PASSWORD, WAITING_MONITOR_USER, 
 WAITING_INTERVAL, CONFIRM_DELETE) = range(5)

class LETMonitorBot:
    def __init__(self, config_path: str = "config.json"):
        """初始化监控机器人"""
        self.config_loader = ConfigLoader(config_path)
        setup_logging(self.config_loader.get_log_config())
        
        self.db = DatabaseManager(
            self.config_loader.get_database_path(),
            self.config_loader
        )
        self.session_manager = SessionManager(self.db, self.config_loader)
        self.monitor_tasks: Dict[int, asyncio.Task] = {}
        
        # 创建主菜单键盘
        self.main_keyboard = [
            [InlineKeyboardButton("➕ 添加监控用户", callback_data='add_user')],
            [InlineKeyboardButton("➖ 删除监控用户", callback_data='remove_user')],
            [InlineKeyboardButton("⚙️ 设置论坛账号", callback_data='set_account')],
            [InlineKeyboardButton("⏰ 设置检查间隔", callback_data='set_interval')],
            [InlineKeyboardButton("📋 查看当前配置", callback_data='show_config')],
            [InlineKeyboardButton("▶️ 开始监控", callback_data='start_monitor')],
            [InlineKeyboardButton("⏹️ 停止监控", callback_data='stop_monitor')]
        ]

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理 /start 命令"""
        if not self.config_loader.is_user_allowed(update.effective_user.id):
            await update.message.reply_text("抱歉，您没有使用此机器人的权限。")
            return ConversationHandler.END
            
        reply_markup = InlineKeyboardMarkup(self.main_keyboard)
        await update.message.reply_text(
            "欢迎使用 LowEndTalk 监控机器人!\n"
            "请选择以下操作：",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理按钮回调"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'add_user':
            await query.message.reply_text(
                "请输入要监控的用户名：\n"
                "（用户名应为 3-20 位的字母、数字、下划线或连字符）"
            )
            return WAITING_MONITOR_USER
            
        elif query.data == 'set_account':
            await query.message.reply_text(
                "请输入论坛用户名："
            )
            return WAITING_USERNAME
            
        elif query.data == 'set_interval':
            await query.message.reply_text(
                "请输入检查间隔时间（秒）：\n"
                "（最小 60 秒，最大 86400 秒）"
            )
            return WAITING_INTERVAL
            
        elif query.data == 'show_config':
            await self.show_config(update.effective_chat.id)
            
        elif query.data == 'start_monitor':
            await self.start_monitoring(update.effective_chat.id)
            
        elif query.data == 'stop_monitor':
            await self.stop_monitoring(update.effective_chat.id)
            
        elif query.data == 'remove_user':
            return await self.show_users_for_removal(update.effective_chat.id)
            
        return ConversationHandler.END

    async def handle_username(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理论坛用户名输入"""
        username = update.message.text.strip()
        
        if not Validators.is_valid_username(username):
            await update.message.reply_text(
                "❌ 用户名格式无效，请重新输入：\n"
                "（用户名应为 3-20 位的字母、数字、下划线或连字符）"
            )
            return WAITING_USERNAME
            
        context.user_data['forum_username'] = username
        await update.message.reply_text("请输入论坛密码：")
        return WAITING_PASSWORD

    async def handle_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理论坛密码输入"""
        # 删除消息以保护密码
        await update.message.delete()
        
        password = update.message.text
        username = context.user_data.get('forum_username')
        chat_id = update.effective_chat.id
        
        # 保存配置
        if not self.db.save_user_config(chat_id, username, password):
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ 保存配置失败，请重试",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return ConversationHandler.END
            
        # 测试登录
        success, message = await self.session_manager.login(chat_id)
        if not success:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {message}\n请重新设置账号",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return ConversationHandler.END
            
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ 论坛账号设置成功！",
            reply_markup=InlineKeyboardMarkup(self.main_keyboard)
        )
        return ConversationHandler.END

    async def handle_monitor_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理添加监控用户"""
        username = update.message.text.strip()
        chat_id = update.effective_chat.id
        
        if not Validators.is_valid_username(username):
            await update.message.reply_text(
                "❌ 用户名格式无效，请重新输入：\n"
                "（用户名应为 3-20 位的字母、数字、下划线或连字符）"
            )
            return WAITING_MONITOR_USER
            
        # 验证用户是否存在
        session = await self.session_manager.get_session(chat_id)
        if not session:
            await update.message.reply_text(
                "❌ 请先设置论坛账号",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return ConversationHandler.END
            
        # 测试访问用户页面
        success, _, message = await self.session_manager.get_user_posts(chat_id, username)
        if not success:
            await update.message.reply_text(
                f"❌ {message}",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return ConversationHandler.END
            
        # 添加监控用户
        if not self.db.add_monitored_user(chat_id, username):
            await update.message.reply_text(
                "❌ 添加用户失败，请重试",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return ConversationHandler.END
            
        await update.message.reply_text(
            f"✅ 已添加监控用户: {username}",
            reply_markup=InlineKeyboardMarkup(self.main_keyboard)
        )
        return ConversationHandler.END

    async def handle_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理检查间隔设置"""
        try:
            interval = int(update.message.text)
            if not Validators.is_valid_interval(interval):
                await update.message.reply_text(
                    "❌ 间隔时间无效，请输入 60-86400 之间的数字（秒）"
                )
                return WAITING_INTERVAL
                
            chat_id = update.effective_chat.id
            config = self.db.get_user_config(chat_id)
            if not config:
                await update.message.reply_text(
                    "❌ 请先设置论坛账号",
                    reply_markup=InlineKeyboardMarkup(self.main_keyboard)
                )
                return ConversationHandler.END
                
            # 更新配置
            self.db.save_user_config(
                chat_id,
                config['forum_username'],
                config['forum_password'],
                interval
            )
            
            await update.message.reply_text(
                f"✅ 检查间隔已设置为 {interval} 秒",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            
        except ValueError:
            await update.message.reply_text(
                "❌ 请输入有效的数字"
            )
            return WAITING_INTERVAL
            
        return ConversationHandler.END

  async def show_config(self, chat_id: int):
        """显示当前配置"""
        config = self.db.get_user_config(chat_id)
        if not config:
            await self.context.bot.send_message(
                chat_id=chat_id,
                text="❌ 未设置论坛账号",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return
            
        users = self.db.get_monitored_users(chat_id)
        users_str = "\n".join([f"- {user[0]}" for user in users]) if users else "无"
        
        message = (
            "📋 当前配置\n\n"
            f"论坛账号: {config['forum_username']}\n"
            f"检查间隔: {config['check_interval']} 秒\n"
            f"\n监控用户列表：\n{users_str}"
        )
        
        await self.context.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=InlineKeyboardMarkup(self.main_keyboard)
        )

    async def show_users_for_removal(self, chat_id: int) -> int:
        """显示可删除的用户列表"""
        users = self.db.get_monitored_users(chat_id)
        if not users:
            await self.context.bot.send_message(
                chat_id=chat_id,
                text="当前没有监控任何用户",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return ConversationHandler.END
            
        keyboard = [
            [InlineKeyboardButton(user[0], callback_data=f'del_{user[0]}')]
            for user in users
        ]
        keyboard.append([InlineKeyboardButton("返回", callback_data='back')])
        
        await self.context.bot.send_message(
            chat_id=chat_id,
            text="选择要删除的用户：",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CONFIRM_DELETE

    async def handle_user_removal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理用户删除"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'back':
            await query.message.edit_text(
                "操作已取消",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return ConversationHandler.END
            
        username = query.data.replace('del_', '')
        chat_id = update.effective_chat.id
        
        if self.db.remove_monitored_user(chat_id, username):
            await query.message.edit_text(
                f"✅ 已删除用户: {username}",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
        else:
            await query.message.edit_text(
                f"❌ 删除用户失败: {username}",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
        
        return ConversationHandler.END

    async def monitor_task(self, chat_id: int):
        """监控任务"""
        try:
            while True:
                config = self.db.get_user_config(chat_id)
                if not config:
                    await self.context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ 未找到配置信息，停止监控",
                        reply_markup=InlineKeyboardMarkup(self.main_keyboard)
                    )
                    return
                    
                users = self.db.get_monitored_users(chat_id)
                for username, last_check in users:
                    success, posts, message = await self.session_manager.get_user_posts(
                        chat_id, username, last_check
                    )
                    
                    if not success:
                        logging.error(f"获取用户 {username} 帖子失败: {message}")
                        continue
                        
                    for post in posts:
                        # 检查是否已存在
                        if not self.db.is_post_exists(post['post_id']):
                            # 保存帖子
                            self.db.save_post(chat_id, post)
                            # 发送通知
                            message = MessageFormatter.format_post_message(
                                post,
                                self.config_loader.get_post_preview_length()
                            )
                            await self.context.bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                disable_web_page_preview=True
                            )




          # 更新最后检查时间
                    if posts:
                        latest_post = max(posts, key=lambda x: x['date'])
                        self.db.update_last_check(chat_id, username, latest_post['date'])
                
                # 等待下一次检查
                await asyncio.sleep(config['check_interval'])
                
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(f"监控任务异常: {str(e)}")
            await self.context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ 监控发生错误: {str(e)}\n已停止监控",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            raise

    async def start_monitoring(self, chat_id: int):
        """启动监控"""
        if chat_id in self.monitor_tasks:
            await self.context.bot.send_message(
                chat_id=chat_id,
                text="监控已在运行中",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return
            
        config = self.db.get_user_config(chat_id)
        if not config:
            await self.context.bot.send_message(
                chat_id=chat_id,
                text="❌ 请先设置论坛账号",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return
            
        users = self.db.get_monitored_users(chat_id)
        if not users:
            await self.context.bot.send_message(
                chat_id=chat_id,
                text="❌ 请先添加要监控的用户",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return
            
        # 测试登录
        if not await self.session_manager.ensure_login(chat_id):
            await self.context.bot.send_message(
                chat_id=chat_id,
                text="❌ 登录失败，请检查账号设置",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return
            
        try:
            # 启动监控任务
            task = asyncio.create_task(self.monitor_task(chat_id))
            self.monitor_tasks[chat_id] = task
            
            message = (
                "✅ 监控已启动\n\n"
                f"当前监控 {len(users)} 个用户\n"
                f"检查间隔: {config['check_interval']} 秒"
            )
            
            await self.context.bot.send_message(
                chat_id=chat_id,
                text=message,
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            
        except Exception as e:
            logging.error(f"启动监控失败: {str(e)}")
            await self.context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ 启动监控失败: {str(e)}",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )

    async def stop_monitoring(self, chat_id: int):
        """停止监控"""
        if chat_id not in self.monitor_tasks:
            await self.context.bot.send_message(
                chat_id=chat_id,
                text="监控未运行",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            return
            
        try:
            # 取消监控任务
            self.monitor_tasks[chat_id].cancel()
            await self.session_manager.close_session(chat_id)
            del self.monitor_tasks[chat_id]
            
            await self.context.bot.send_message(
                chat_id=chat_id,
                text="✅ 监控已停止",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )
            
        except Exception as e:
            logging.error(f"停止监控失败: {str(e)}")
            await self.context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ 停止监控失败: {str(e)}",
                reply_markup=InlineKeyboardMarkup(self.main_keyboard)
            )

    async def cleanup(self):
        """清理资源"""
        # 停止所有监控任务
        for chat_id in list(self.monitor_tasks.keys()):
            await self.stop_monitoring(chat_id)
        
        # 关闭所有会话
        await self.session_manager.cleanup()

def main():
    """主函数"""
    # 创建机器人实例
    bot = LETMonitorBot()
    
    # 创建应用
    application = Application.builder().token(
        bot.config_loader.get_bot_config().token
    ).build()
    
    # 添加处理器
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', bot.start),
            CallbackQueryHandler(bot.button_handler)
        ],
        states={
            WAITING_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_username)
            ],
            WAITING_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_password)
            ],
            WAITING_MONITOR_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_monitor_user)
            ],
            WAITING_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_interval)
            ],
            CONFIRM_DELETE: [
                CallbackQueryHandler(bot.handle_user_removal)
            ],
        },
        fallbacks=[
            CommandHandler('cancel', lambda u, c: ConversationHandler.END),
            CallbackQueryHandler(bot.button_handler)
        ]
    )
    
    application.add_handler(conv_handler)
    
    # 设置优雅关闭
    async def shutdown(application: Application):
        await bot.cleanup()
        await application.stop()
        await application.shutdown()
    
    # 启动机器人
    try:
        application.run_polling()
    except KeyboardInterrupt:
        print("正在关闭机器人...")
        asyncio.run(shutdown(application))
        print("机器人已关闭")

if __name__ == '__main__':
    main()
