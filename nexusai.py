import os
import io
import logging
import json
import threading
import time
import re
import asyncio
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from collections import defaultdict

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from PIL import Image
import requests

load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables!")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in environment variables!")

DRIFT_API_URL = os.getenv("DRIFT_API_URL", "https://drift-ai-api.vercel.app/ask")
DRIFT_API_KEY = os.getenv("DRIFT_API_KEY", "drift")

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
KEEP_ALIVE_INTERVAL = int(os.getenv("KEEP_ALIVE_INTERVAL", "300"))

ADMIN_IDS = []
admin_ids_str = os.getenv("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]

# Force Join Channels (with IDs for reliable checking)
REQUIRED_CHANNELS = []
for i in range(1, 10):
    username = os.getenv(f"CHANNEL_{i}_USERNAME")
    link = os.getenv(f"CHANNEL_{i}_LINK")
    channel_id = os.getenv(f"CHANNEL_{i}_ID")
    if username and link:
        REQUIRED_CHANNELS.append({
            "username": username,
            "link": link,
            "id": channel_id
        })

# Default channels if none configured
if not REQUIRED_CHANNELS:
    REQUIRED_CHANNELS = [
        {"username": "NCKDEVFreeSC", "link": "https://t.me/NCKDEVFreeSC", "id": "-1003637300526"},
        {"username": "ERRORX404E", "link": "https://t.me/ERRORX404E", "id": "-1004384280494"},
        {"username": "NCK_Dev", "link": "https://t.me/NCK_Dev", "id": None}
    ]

VERIFICATION_HOURS = int(os.getenv("VERIFICATION_HOURS", "1"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", "5"))
MAX_MESSAGES_PER_MINUTE = int(os.getenv("MAX_MESSAGES_PER_MINUTE", "10"))

# ============================================================================
# LOGGING
# ============================================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL.upper())
)
logger = logging.getLogger(__name__)

logger.info("🚀 Starting Nexus AI Bot...")

# ============================================================================
# HEALTH SERVER + KEEP-ALIVE PING
# ============================================================================
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK - Nexus AI Bot is running')
    
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    
    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.getenv('PORT', 10000))
    try:
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"✅ Health server running on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.warning(f"⚠️ Health server error: {e}")

def keep_alive_ping():
    """Ping the app URL every KEEP_ALIVE_INTERVAL seconds to keep it awake"""
    if not RENDER_EXTERNAL_URL:
        logger.info("ℹ️ KEEP_ALIVE: RENDER_EXTERNAL_URL not set, skipping keep-alive ping")
        return
    
    logger.info(f"🔄 Keep-alive started (interval: {KEEP_ALIVE_INTERVAL}s, URL: {RENDER_EXTERNAL_URL})")
    
    while True:
        try:
            time.sleep(KEEP_ALIVE_INTERVAL)
            response = requests.get(RENDER_EXTERNAL_URL, timeout=10)
            if response.status_code == 200:
                logger.info(f"💓 Keep-alive ping successful at {datetime.now().strftime('%H:%M:%S')}")
            else:
                logger.warning(f"⚠️ Keep-alive ping returned status {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Keep-alive ping failed: {e}")

# Start health server thread
health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()

# Start keep-alive thread
keep_alive_thread = threading.Thread(target=keep_alive_ping, daemon=True)
keep_alive_thread.start()

# ============================================================================
# HTML FORMATTER
# ============================================================================
class HTMLFormatter:
    """Format responses using HTML for Telegram - Clean style without separators"""
    
    @staticmethod
    def format_response(text: str) -> str:
        """Format text using HTML tags with clean style"""
        text = text.strip()
        
        if len(text.split()) > 50 and not text.startswith('🤔'):
            text = "🤔 <b>Let me think about this...</b>\n\n" + text
        
        # Remove separators
        text = re.sub(r'━{2,}', '', text)
        text = re.sub(r'─{2,}', '', text)
        text = re.sub(r'---+\s*', '', text)
        text = re.sub(r'—+', '', text)
        
        # Convert markdown to HTML
        text = re.sub(r'\*\*([^*]+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__([^_]+?)__', r'<i>\1</i>', text)
        
        # Convert headers
        text = re.sub(r'^# (.*?)$', r'<b>📌 \1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'^## (.*?)$', r'<b>▸ \1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'^### (.*?)$', r'<b>◦ \1</b>', text, flags=re.MULTILINE)
        
        # Convert tables
        text = HTMLFormatter._format_tables(text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Format lists
        lines = text.split('\n')
        formatted_lines = []
        in_list = False
        list_type = None
        list_counter = 1
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            if not line and i == 0:
                continue
            
            if line in ['---', '—', '━', '─'] or re.match(r'^[-—━─]{2,}$', line):
                continue
            
            numbered_match = re.match(r'^(\d+)\.\s+(.*)', line)
            if numbered_match:
                if not in_list or list_type != 'numbered':
                    if in_list:
                        formatted_lines.append('')
                    list_type = 'numbered'
                    list_counter = 1
                    in_list = True
                formatted_lines.append(f"{list_counter}. {numbered_match.group(2)}")
                list_counter += 1
                continue
            
            bullet_match = re.match(r'^[-•]\s+(.*)', line)
            if bullet_match:
                if not in_list or list_type != 'bullet':
                    if in_list:
                        formatted_lines.append('')
                    list_type = 'bullet'
                    in_list = True
                formatted_lines.append(f"• {bullet_match.group(1)}")
                continue
            
            if in_list and line and not re.match(r'^(\d+\.|[-•])\s+', line):
                in_list = False
                list_type = None
            
            line = HTMLFormatter._format_inline(line)
            formatted_lines.append(line)
        
        result = '\n'.join(formatted_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)
        result = re.sub(r'\n\s*---+\s*\n', '\n\n', result)
        result = re.sub(r'^---+\s*\n', '', result)
        result = re.sub(r'\n---+\s*$', '', result)
        
        if len(result.split()) > 40 and not result.endswith('🚀'):
            if 'Need more help' not in result:
                result += "\n\n💡 <b>Need more help? Just ask!</b> 🚀"
        
        return result
    
    @staticmethod
    def _format_tables(text: str) -> str:
        """Convert markdown tables to readable format"""
        lines = text.split('\n')
        result = []
        in_table = False
        table_lines = []
        
        for line in lines:
            if '|' in line and line.strip().startswith('|'):
                in_table = True
                table_lines.append(line)
            else:
                if in_table and table_lines:
                    result.append(HTMLFormatter._process_table(table_lines))
                    table_lines = []
                    in_table = False
                result.append(line)
        
        if in_table and table_lines:
            result.append(HTMLFormatter._process_table(table_lines))
        
        return '\n'.join(result)
    
    @staticmethod
    def _process_table(table_lines: List[str]) -> str:
        """Process a markdown table into readable text"""
        if len(table_lines) < 2:
            return '\n'.join(table_lines)
        
        headers = [h.strip() for h in table_lines[0].strip('|').split('|')]
        
        rows = []
        for line in table_lines[2:]:
            if '|' in line:
                cells = [c.strip() for c in line.strip('|').split('|')]
                if cells and any(cells):
                    rows.append(cells)
        
        if not rows:
            return '\n'.join(table_lines)
        
        result = []
        result.append("📋 <b>" + " | ".join(headers) + "</b>")
        for row in rows[:5]:
            result.append("• " + " | ".join(row))
        
        if len(rows) > 5:
            result.append(f"• ... and {len(rows) - 5} more rows")
        
        return '\n'.join(result)
    
    @staticmethod
    def _format_inline(text: str) -> str:
        """Format inline elements with HTML"""
        text = re.sub(r'```(\w+)?\n(.*?)\n```', r'<pre><code>\2</code></pre>', text, flags=re.DOTALL)
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
        text = re.sub(r'\*\*([^*]+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__([^_]+?)__', r'<i>\1</i>', text)
        text = re.sub(r'(?<!\w)\*([^*]+?)\*(?!\w)', r'<i>\1</i>', text)
        return text

# ============================================================================
# DRIFT API INTEGRATION
# ============================================================================
class DriftAPI:
    """Integration with Drift AI API for DeepSeek and ChatGPT models"""
    
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key
        self.available_models = []
        self.models_status = {}
        self._check_models()
    
    def _check_models(self):
        """Check which models are available via the API"""
        test_models = ["deepseek", "gpt-oss"]
        
        for model_type in test_models:
            try:
                response = requests.get(
                    self.api_url,
                    params={"q": "test", "key": self.api_key, "type": model_type},
                    timeout=5
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        self.available_models.append(model_type)
                        self.models_status[model_type] = True
                        logger.info(f"✅ Drift API - {model_type} is available")
                    else:
                        self.models_status[model_type] = False
                else:
                    self.models_status[model_type] = False
            except Exception as e:
                logger.warning(f"⚠️ Drift API - {model_type} not available: {e}")
                self.models_status[model_type] = False
    
    def query(self, prompt: str, model_type: str) -> Optional[str]:
        """Query the Drift API with a prompt"""
        if model_type not in self.available_models:
            return None
        
        try:
            response = requests.get(
                self.api_url,
                params={"q": prompt, "key": self.api_key, "type": model_type},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data.get("reply", "")
                else:
                    return None
            else:
                return None
        except Exception as e:
            logger.error(f"Drift API error: {e}")
            return None
    
    def is_available(self, model_type: str) -> bool:
        """Check if a specific model is available"""
        return model_type in self.available_models

# ============================================================================
# GROQ AI CLASS WITH DRIFT INTEGRATION & FALLBACK
# ============================================================================
class GroqAI:
    def __init__(self):
        logger.info("🔄 Initializing Groq AI...")
        
        self.api_key = GROQ_API_KEY
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        
        self.drift = DriftAPI(DRIFT_API_URL, DRIFT_API_KEY)
        
        self.groq_limit_reached = False
        self.groq_limit_reset_time = None
        
        self.base_models = {
            "llama-3.3-70b": {
                "name": "Llama 3.3 70B",
                "model": "llama-3.3-70b-versatile",
                "description": "🧠 Most Powerful",
                "speed": "⚡ Fast",
                "context": "📏 128K",
                "provider": "Groq"
            },
            "llama-3.1-8b": {
                "name": "Llama 3.1 8B",
                "model": "llama-3.1-8b-instant",
                "description": "🚀 Fastest",
                "speed": "⚡ Ultra Fast",
                "context": "📏 128K",
                "provider": "Groq"
            },
            "mixtral-8x7b": {
                "name": "Mixtral 8x7B",
                "model": "mixtral-8x7b-32768",
                "description": "⚖️ Balanced",
                "speed": "⚡ Medium",
                "context": "📏 32K",
                "provider": "Groq"
            }
        }
        
        self.drift_models = {}
        if self.drift.is_available("deepseek"):
            self.drift_models["deepseek"] = {
                "name": "DeepSeek V3.1",
                "model": "deepseek",
                "description": "🧠 Advanced Reasoning",
                "speed": "⚡ Fast",
                "context": "📏 128K",
                "provider": "Drift AI"
            }
        
        if self.drift.is_available("gpt-oss"):
            self.drift_models["gpt-oss"] = {
                "name": "GPT-OSS 120B",
                "model": "gpt-oss",
                "description": "💡 Creative & Analytical",
                "speed": "⚡ Fast",
                "context": "📏 32K",
                "provider": "Drift AI"
            }
        
        self.models = {**self.base_models, **self.drift_models}
        self.current_model = "llama-3.1-8b"
        
        self.user_sessions = {}
        self.verified_users = {}
        self.user_cooldowns = {}
        self.user_message_counts = {}
        self.user_reset_time = {}
        self.user_ratings = defaultdict(list)
        self.last_response = {}
        self.model_stats = defaultdict(int)
        
        logger.info(f"✅ Groq AI ready with {len(self.models)} models!")
        logger.info(f"📋 Available models: {list(self.models.keys())}")
    
    def _call_groq_api(self, messages: List[dict]) -> Tuple[str, bool]:
        """Call Groq API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": self.models[self.current_model]["model"],
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1000,
            "top_p": 0.9
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=data, timeout=60)
            
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"], False
            elif response.status_code == 429:
                error_msg = response.text.lower()
                if "quota" in error_msg or "daily" in error_msg:
                    self.groq_limit_reached = True
                    self.groq_limit_reset_time = datetime.now() + timedelta(days=1)
                    return "🚫 <b>Daily Limit Reached</b>\n\nThe Groq service has reached its daily limit.", True
                else:
                    retry_after = 60
                    try:
                        retry_after = int(response.headers.get('retry-after', 60))
                    except:
                        pass
                    return f"🔄 <b>Service Busy</b>\n\nPlease wait: {retry_after} seconds", False
            else:
                return "❌ <b>Something went wrong</b>\n\nPlease try again later.", False
                
        except requests.exceptions.Timeout:
            return "⏰ <b>Timeout</b>\n\nThe AI service is taking too long.", False
        except Exception as e:
            logger.error(f"API error: {e}")
            return "❌ <b>Error</b>\n\nSomething went wrong.", False
    
    def chat(self, prompt: str, user_id: int) -> str:
        """Generate chat response with fallback"""
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = []
        
        history = self.user_sessions[user_id]
        
        current_model_info = self.models[self.current_model]
        is_drift_model = current_model_info.get("provider") == "Drift AI"
        
        if is_drift_model:
            result = self._call_drift_api(prompt)
            self.user_sessions[user_id].append({"role": "user", "content": prompt})
            self.user_sessions[user_id].append({"role": "assistant", "content": result})
            self.last_response[user_id] = result
            self.model_stats[self.current_model] += 1
            return result
        
        if self.groq_limit_reached:
            if self.groq_limit_reset_time and datetime.now() > self.groq_limit_reset_time:
                self.groq_limit_reached = False
            else:
                drift_models = [k for k, v in self.models.items() if v.get('provider') == 'Drift AI']
                if drift_models:
                    fallback_model = drift_models[0]
                    old_model = self.current_model
                    self.current_model = fallback_model
                    result = self._call_drift_api(prompt)
                    self.current_model = old_model
                    
                    fallback_name = self.models[fallback_model]['name']
                    warning = f"⚠️ <b>Groq limit reached. Using {fallback_name} as fallback.</b>\n\n"
                    result = warning + result
                    
                    self.user_sessions[user_id].append({"role": "user", "content": prompt})
                    self.user_sessions[user_id].append({"role": "assistant", "content": result})
                    self.last_response[user_id] = result
                    self.model_stats[fallback_model] += 1
                    return result
                else:
                    return "🚫 <b>All AI services are currently unavailable</b>\n\nPlease try again later."
        
        system_prompt = """You are Nexus AI, a helpful assistant.

RESPONSE STYLE:
- Be clear, structured, and detailed
- Use markdown for formatting (**, *, `, etc.)
- Break down complex topics
- Provide examples when helpful
- Use emojis for visual appeal
- Use bullet points and numbered lists
- Keep responses clean and not too verbose
- Use tables for comparing data when helpful

FORMATTING RULES:
- Use **bold** for emphasis
- Use `code` for technical terms
- Use * for bullet points
- Use numbers for steps
- Use ✅ for completed items
- Use ⚠️ for warnings
- Use 💡 for tips"""
        
        messages = [{"role": "system", "content": system_prompt}]
        
        for msg in history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        messages.append({"role": "user", "content": prompt})
        
        result, is_limit = self._call_groq_api(messages)
        
        if is_limit:
            drift_models = [k for k, v in self.models.items() if v.get('provider') == 'Drift AI']
            if drift_models:
                fallback_model = drift_models[0]
                old_model = self.current_model
                self.current_model = fallback_model
                result = self._call_drift_api(prompt)
                self.current_model = old_model
                
                fallback_name = self.models[fallback_model]['name']
                result = f"⚠️ <b>Groq limit reached. Using {fallback_name} as fallback.</b>\n\n{result}"
                self.model_stats[fallback_model] += 1
            else:
                result = "🚫 <b>Groq limit reached and no fallback models available.</b>\n\nPlease try again later."
        
        result = HTMLFormatter.format_response(result)
        
        self.user_sessions[user_id].append({"role": "user", "content": prompt})
        self.user_sessions[user_id].append({"role": "assistant", "content": result})
        self.last_response[user_id] = result
        self.model_stats[self.current_model] += 1
        
        return result
    
    def _call_drift_api(self, prompt: str) -> str:
        """Call Drift API"""
        model_type = self.models[self.current_model]["model"]
        response = self.drift.query(prompt, model_type)
        
        if response is not None:
            return response
        else:
            return "❌ <b>API Error</b>\n\nThe Drift AI service is currently unavailable."
    
    def check_rate_limit(self, user_id: int) -> Tuple[bool, str]:
        """Check rate limit"""
        now = time.time()
        
        if user_id in self.user_cooldowns:
            time_since_last = now - self.user_cooldowns[user_id]
            if time_since_last < RATE_LIMIT_SECONDS:
                return False, f"⏳ Please wait {RATE_LIMIT_SECONDS - int(time_since_last)} seconds before sending another message."
        
        if user_id not in self.user_reset_time or now - self.user_reset_time[user_id] > 60:
            self.user_message_counts[user_id] = 0
            self.user_reset_time[user_id] = now
        
        self.user_message_counts[user_id] = self.user_message_counts.get(user_id, 0) + 1
        if self.user_message_counts[user_id] > MAX_MESSAGES_PER_MINUTE:
            return False, "📊 <b>Rate Limit Exceeded</b>\n\nYou've reached the maximum messages per minute. Please wait a moment."
        
        self.user_cooldowns[user_id] = now
        return True, ""
    
    def save_rating(self, user_id: int, rating: int):
        """Save user rating"""
        self.user_ratings[user_id].append(rating)
        try:
            ratings = []
            try:
                with open("ratings.json", "r") as f:
                    for line in f:
                        if line.strip():
                            ratings.append(json.loads(line))
            except:
                pass
            
            ratings.append({"user": user_id, "rating": rating, "time": time.time()})
            
            with open("ratings.json", "w") as f:
                for r in ratings:
                    json.dump(r, f)
                    f.write("\n")
        except Exception as e:
            logger.error(f"Error saving rating: {e}")

ai = GroqAI()

# ============================================================================
# USER MANAGEMENT
# ============================================================================
async def get_all_users() -> List[int]:
    try:
        with open("users.json", "r") as file:
            return json.load(file)
    except:
        return []

async def save_user(user_id: int):
    users = await get_all_users()
    if user_id not in users:
        users.append(user_id)
        with open("users.json", "w") as file:
            json.dump(users, file)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ============================================================================
# FORCE JOIN SYSTEM
# ============================================================================
async def check_user_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, List[dict]]:
    not_joined = []
    for channel in REQUIRED_CHANNELS:
        username = channel["username"]
        channel_id = channel.get("id")
        joined = False
        
        # Try by ID first (more reliable)
        if channel_id:
            try:
                chat_member = await context.bot.get_chat_member(
                    chat_id=int(channel_id),
                    user_id=user_id
                )
                if chat_member.status in ["member", "administrator", "creator"]:
                    joined = True
            except Exception:
                pass
        
        # Fallback to username
        if not joined:
            try:
                chat_member = await context.bot.get_chat_member(
                    chat_id=f"@{username}",
                    user_id=user_id
                )
                if chat_member.status in ["member", "administrator", "creator"]:
                    joined = True
            except Exception:
                pass
        
        if not joined:
            not_joined.append(channel)
    
    return len(not_joined) == 0, not_joined

async def get_join_keyboard(not_joined: List[dict] = None) -> InlineKeyboardMarkup:
    keyboard = []
    for channel in REQUIRED_CHANNELS:
        if not_joined is None or any(c["username"] == channel["username"] for c in not_joined):
            keyboard.append([
                InlineKeyboardButton(
                    f"📢 Join {channel['username']}",
                    url=channel["link"]
                )
            ])
    keyboard.append([
        InlineKeyboardButton(
            "✅ Verify & Activate",
            callback_data="check_subscription"
        )
    ])
    return InlineKeyboardMarkup(keyboard)

async def send_force_join_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    first_name = user.first_name if user.first_name else "User"
    _, not_joined = await check_user_subscription(user.id, context)
    
    message = (
        f"👋 <b>Hello {first_name}! Welcome to NEXUS AI</b>\n\n"
        f"📢 <b>Please join these channels to activate me:</b>\n\n"
    )
    
    for channel in REQUIRED_CHANNELS:
        is_joined = not any(c["username"] == channel["username"] for c in not_joined)
        status = "✅" if is_joined else "❌"
        message += f"{status} <a href='{channel['link']}'>{channel['username']}</a>\n"
    
    message += "\n🔓 <b>Click below to activate!</b>"
    
    keyboard = await get_join_keyboard(not_joined)
    
    if update.message:
        await update.message.reply_text(
            message,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    elif update.callback_query:
        await update.callback_query.message.edit_text(
            message,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

async def force_join_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if is_admin(user_id):
        return True
    if user_id in ai.verified_users:
        if datetime.now() - ai.verified_users[user_id] < timedelta(hours=VERIFICATION_HOURS):
            return True
    is_subscribed, _ = await check_user_subscription(user_id, context)
    if is_subscribed:
        ai.verified_users[user_id] = datetime.now()
        return True
    await send_force_join_message(update, context)
    return False

# ============================================================================
# MAIN MENU
# ============================================================================
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, first_time: bool = False):
    user = update.effective_user
    first_name = user.first_name if user.first_name else "User"
    model_name = ai.models[ai.current_model]['name']
    provider = ai.models[ai.current_model].get('provider', 'Groq')
    
    groq_status = "⚠️ Limit Reached" if ai.groq_limit_reached else "✅ Active"
    
    if first_time:
        welcome_text = (
            f"🎉 <b>Welcome {first_name}!</b>\n\n"
            f"✨ <b>Nexus AI</b>\n"
            f"🤖 <b>Using:</b> {model_name}\n"
            f"🔌 <b>Provider:</b> {provider}\n"
            f"📊 <b>Groq Status:</b> {groq_status}\n\n"
            f"💡 <b>I can help you with:</b>\n"
            f"• Answering questions\n"
            f"• Creative writing\n"
            f"• Problem solving\n"
            f"• Learning new topics\n\n"
            f"🚀 <b>Let's get started!</b>"
        )
    else:
        welcome_text = (
            f"👋 <b>Welcome back {first_name}!</b>\n\n"
            f"🤖 <b>Nexus AI - {model_name}</b>\n"
            f"🔌 <b>Provider:</b> {provider}\n"
            f"📊 <b>Groq Status:</b> {groq_status}\n\n"
            f"📌 <b>What would you like to do?</b>"
        )
    
    keyboard = [
        [InlineKeyboardButton("💬 Chat", callback_data="chat_mode")],
        [InlineKeyboardButton("🔧 Select Model", callback_data="model_select")],
        [InlineKeyboardButton("📚 History", callback_data="history_view")],
        [InlineKeyboardButton("❓ Help", callback_data="help_menu")]
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Admin", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, parse_mode="HTML", reply_markup=reply_markup)

# ============================================================================
# START COMMAND
# ============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await save_user(user.id)
    logger.info(f"👤 User {user.id} started the bot")
    if not await force_join_check(update, context):
        return
    await show_main_menu(update, context, first_time=True)

# ============================================================================
# CLEAR HISTORY COMMAND
# ============================================================================
async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await force_join_check(update, context):
        return
    
    if user_id in ai.user_sessions:
        ai.user_sessions[user_id] = []
        await update.message.reply_text(
            "🧹 <b>Chat history cleared!</b>\n\nYour conversation history has been reset. Let's start fresh! ✨",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Menu", callback_data="main_menu")]])
        )
    else:
        await update.message.reply_text(
            "ℹ️ <b>No chat history found</b>\n\nYou don't have any conversation history to clear.",
            parse_mode="HTML"
        )

# ============================================================================
# ADMIN COMMANDS
# ============================================================================
async def admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <b>Access denied!</b>", parse_mode="HTML")
        return
    
    cmd = update.message.text[1:] if update.message.text.startswith('/') else ''
    
    if cmd == 'stats':
        users = await get_all_users()
        await update.message.reply_text(
            f"📊 <b>Bot Statistics</b>\n\n"
            f"👥 Total Users: {len(users)}\n"
            f"🤖 Model: {ai.models[ai.current_model]['name']}\n"
            f"📊 Groq Status: {'⚠️ Limit Reached' if ai.groq_limit_reached else '✅ Active'}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 Full Stats", callback_data="admin_stats")]])
        )
    elif cmd == 'users':
        users = await get_all_users()
        user_list = "\n".join([f"• <code>{uid}</code>" for uid in users[:20]])
        await update.message.reply_text(
            f"👥 <b>Users ({len(users)})</b>\n\n{user_list}",
            parse_mode="HTML"
        )
    elif cmd == 'broadcast':
        context.user_data['broadcast_step'] = 'media'
        await update.message.reply_text(
            "📢 <b>Broadcast Message</b>\n\n"
            "Send an image (optional) or caption text.\n\n"
            "📌 <b>Format for buttons:</b>\n"
            "<code>Text | URL</code> (one per line)\n\n"
            "📝 <b>Example:</b>\n"
            "<code>Visit Website | https://example.com</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]])
        )

# ============================================================================
# CALLBACK HANDLER
# ============================================================================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    
    # Handle subscription check
    if data == "check_subscription":
        is_subscribed, not_joined = await check_user_subscription(user_id, context)
        if is_subscribed:
            ai.verified_users[user_id] = datetime.now()
            user = update.effective_user
            first_name = user.first_name if user.first_name else "User"
            await query.edit_message_text(
                f"✅ <b>Verified!</b>\n\n🎉 Thank you {first_name}!\n\n🤖 You can now use Nexus AI.",
                parse_mode="HTML"
            )
            await show_main_menu(update, context, first_time=True)
        else:
            message = "📢 <b>Join these channels:</b>\n\n"
            for channel in REQUIRED_CHANNELS:
                is_joined = not any(c["username"] == channel["username"] for c in not_joined)
                status = "✅" if is_joined else "❌"
                message += f"{status} <a href='{channel['link']}'>{channel['username']}</a>\n"
            keyboard = await get_join_keyboard(not_joined)
            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        return
    
    # Handle fallback model selection
    if data.startswith("fallback_model_"):
        model_key = data.replace("fallback_model_", "")
        
        if model_key in ai.models:
            ai.current_model = model_key
            model = ai.models[model_key]
            
            await query.edit_message_text(
                f"✅ <b>Switched to {model['name']}</b>\n\n"
                f"🔌 <b>Provider:</b> {model.get('provider', 'Unknown')}\n"
                f"📌 <b>Description:</b> {model['description']}\n\n"
                f"✨ You can now continue chatting with this model!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Chat", callback_data="chat_mode")]])
            )
        return
    
    # Handle main menu
    if data == "main_menu":
        if not await force_join_check(update, context):
            return
        await show_main_menu(update, context, first_time=False)
        return
    
    # Handle history view
    if data == "history_view":
        if not await force_join_check(update, context):
            return
        if user_id not in ai.user_sessions or not ai.user_sessions[user_id]:
            await query.edit_message_text(
                "📚 <b>Chat History</b>\n\nYou don't have any chat history yet.\nStart chatting to build your history! 💬",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Menu", callback_data="main_menu")]])
            )
            return
        
        history = ai.user_sessions[user_id][-10:]
        history_text = "📚 <b>Your Recent Chat History</b>\n\n"
        for msg in history:
            role = "👤 You" if msg["role"] == "user" else "🤖 Nexus AI"
            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            history_text += f"<b>{role}:</b> {content}\n\n"
        
        await query.edit_message_text(
            history_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧹 Clear History", callback_data="clear_history_confirm")],
                [InlineKeyboardButton("📋 Menu", callback_data="main_menu")]
            ])
        )
        return
    
    # Handle clear history
    if data == "clear_history_confirm":
        if not await force_join_check(update, context):
            return
        if user_id in ai.user_sessions:
            ai.user_sessions[user_id] = []
            await query.edit_message_text(
                "🧹 <b>Chat history cleared!</b>\n\nYour conversation history has been reset. ✨",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Menu", callback_data="main_menu")]])
            )
        return
    
    # Handle model selection
    if data == "model_select":
        if not await force_join_check(update, context):
            return
        keyboard = []
        for key, model in ai.models.items():
            is_current = "✅ " if key == ai.current_model else "  "
            provider = model.get('provider', 'Groq')
            keyboard.append([
                InlineKeyboardButton(
                    f"{is_current}{model['name']} [{provider}]",
                    callback_data=f"set_model_{key}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
        await query.edit_message_text(
            f"🔧 <b>Select Model</b>\n\n"
            f"📌 <b>Current:</b> {ai.models[ai.current_model]['name']}\n"
            f"🔌 <b>Provider:</b> {ai.models[ai.current_model].get('provider', 'Groq')}\n\n"
            f"⚡ <b>Choose a model:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Handle set model
    if data.startswith("set_model_"):
        if not await force_join_check(update, context):
            return
        model_key = data.replace("set_model_", "")
        if model_key in ai.models:
            ai.current_model = model_key
            model = ai.models[model_key]
            await query.edit_message_text(
                f"✅ <b>Switched to {model['name']}</b>\n\n"
                f"📌 <b>Description:</b> {model['description']}\n"
                f"⚡ <b>Speed:</b> {model['speed']}\n"
                f"📊 <b>Context:</b> {model['context']}\n"
                f"🔌 <b>Provider:</b> {model.get('provider', 'Groq')}\n\n"
                f"✨ Model loaded successfully!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]])
            )
        return
    
    # Handle chat mode
    if data == "chat_mode":
        if not await force_join_check(update, context):
            return
        context.user_data['mode'] = 'chat'
        model_name = ai.models[ai.current_model]['name']
        await query.edit_message_text(
            f"💬 <b>Chat Mode</b>\n\n"
            f"🤖 <b>Using:</b> {model_name}\n\n"
            f"✨ <b>Send me any message and I'll reply!</b>\n\n"
            f"💡 <b>I can help with:</b>\n"
            f"• Questions & answers\n"
            f"• Writing & coding\n"
            f"• Research & learning\n"
            f"• General tasks\n\n"
            f"📝 <b>Type your message now</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]])
        )
        return
    
    # Handle help menu
    if data == "help_menu":
        if not await force_join_check(update, context):
            return
        help_text = (
            f"❓ <b>Help Center</b>\n\n"
            f"💬 <b>Chat</b>\n"
            f"Send any text message for intelligent responses\n\n"
            f"🔧 <b>Model Selection</b>\n"
            f"Choose from multiple AI models:\n"
            f"• Groq Llama models\n"
            f"• DeepSeek V3.1\n"
            f"• GPT-OSS 120B\n\n"
            f"📚 <b>History</b>\n"
            f"View and clear your conversation history\n\n"
            f"⚡ <b>Powered by Groq & Drift AI</b>\n"
            f"Ultra-fast AI responses\n\n"
            f"💡 <b>Tips</b>\n"
            f"• Be specific with questions\n"
            f"• Use clear language\n"
            f"• Ask follow-up questions\n\n"
            f"Just type your message! 🚀"
        )
        await query.edit_message_text(
            help_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]])
        )
        return
    
    # Handle admin panel
    if data == "admin_panel":
        if not is_admin(user_id):
            await query.edit_message_text("⛔ <b>Access denied!</b>", parse_mode="HTML")
            return
        await query.edit_message_text(
            "⚙️ <b>Admin Panel</b>\n\nSelect an option:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
                [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
                [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
                [InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]
            ])
        )
        return
    
    # Handle admin stats
    if data == "admin_stats":
        if not is_admin(user_id):
            return
        users = await get_all_users()
        
        avg_rating = 0
        try:
            with open("ratings.json", "r") as f:
                ratings = [json.loads(line) for line in f if line.strip()]
                if ratings:
                    avg_rating = sum(int(r['rating']) for r in ratings) / len(ratings)
        except:
            pass
        
        model_usage = "\n".join([f"• {ai.models[k]['name']}: {v} uses" for k, v in ai.model_stats.items()])
        
        await query.edit_message_text(
            f"📊 <b>Bot Statistics</b>\n\n"
            f"👥 Total Users: {len(users)}\n"
            f"⭐ Avg Rating: {avg_rating:.1f}/5\n"
            f"🤖 Current Model: {ai.models[ai.current_model]['name']}\n"
            f"📊 Model Usage:\n{model_usage}\n"
            f"💓 Keep-Alive: {'✅ Active' if RENDER_EXTERNAL_URL else '❌ Disabled'}\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]])
        )
        return
    
    # Handle admin users
    if data == "admin_users":
        if not is_admin(user_id):
            return
        users = await get_all_users()
        if not users:
            await query.edit_message_text("👥 <b>No users found.</b>", parse_mode="HTML")
            return
        user_list = "\n".join([f"• <code>{uid}</code>" for uid in users[:20]])
        await query.edit_message_text(
            f"👥 <b>Users ({len(users)})</b>\n\n{user_list}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]])
        )
        return
    
    # Handle admin broadcast
    if data == "admin_broadcast":
        if not is_admin(user_id):
            return
        context.user_data['broadcast_step'] = 'media'
        await query.edit_message_text(
            "📢 <b>Broadcast</b>\n\n"
            "Send an image (optional) or caption text.\n\n"
            "📌 <b>Format for buttons:</b>\n"
            "<code>Text | URL</code> (one per line)",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]])
        )
        return
    
    # Handle cancel broadcast
    if data == "cancel_broadcast":
        for k in ['broadcast_step', 'broadcast_image', 'broadcast_caption', 'broadcast_buttons']:
            context.user_data.pop(k, None)
        await query.edit_message_text(
            "❌ <b>Cancelled</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]])
        )
        return
    
    # Handle confirm broadcast
    if data == "confirm_broadcast":
        if not is_admin(user_id):
            return
        users = await get_all_users()
        caption = context.user_data.get('broadcast_caption', '')
        buttons = context.user_data.get('broadcast_buttons', [])
        img_data = context.user_data.get('broadcast_image')
        reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
        
        await query.edit_message_text(f"📤 Sending to {len(users)} users...", parse_mode="HTML")
        success, failed = 0, 0
        
        for uid in users:
            try:
                if img_data:
                    img = Image.open(io.BytesIO(img_data))
                    b = io.BytesIO()
                    img.save(b, format="PNG")
                    b.seek(0)
                    await context.bot.send_photo(
                        chat_id=uid,
                        photo=b,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
                else:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
                success += 1
            except Exception as e:
                failed += 1
                logger.error(f"Failed {uid}: {e}")
        
        for k in ['broadcast_step', 'broadcast_image', 'broadcast_caption', 'broadcast_buttons']:
            context.user_data.pop(k, None)
        
        await query.message.reply_text(
            f"✅ <b>Broadcast Complete</b>\n\n"
            f"✅ Success: {success}\n"
            f"❌ Failed: {failed}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]])
        )
        return
    
    # Handle rate prompt
    if data == "rate_prompt":
        if not await force_join_check(update, context):
            return
        
        if user_id not in ai.last_response:
            await query.edit_message_text(
                "❌ <b>No response to rate</b>\n\nPlease send a message first, then rate the response.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Menu", callback_data="main_menu")]])
            )
            return
        
        keyboard = [
            [
                InlineKeyboardButton("⭐", callback_data="rate_1"),
                InlineKeyboardButton("⭐", callback_data="rate_2"),
                InlineKeyboardButton("⭐", callback_data="rate_3"),
                InlineKeyboardButton("⭐", callback_data="rate_4"),
                InlineKeyboardButton("⭐", callback_data="rate_5")
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            "⭐ <b>Rate this response</b>\n\n"
            "How helpful was this response?\n"
            "<i>Click a star to rate (1-5)</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Handle rating
    if data.startswith("rate_"):
        if not await force_join_check(update, context):
            return
        
        rating_str = data.replace("rate_", "")
        
        if rating_str.isdigit():
            rating = int(rating_str)
            
            if 1 <= rating <= 5:
                ai.save_rating(user_id, rating)
                
                stars = "⭐" * rating
                await query.edit_message_text(
                    f"{stars} <b>Thanks for your rating!</b>\n\n"
                    f"You rated this response {rating} out of 5.\n"
                    f"Your feedback helps us improve! 🚀",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Menu", callback_data="main_menu")]])
                )
            else:
                await query.edit_message_text(
                    "❌ <b>Invalid rating</b>\n\nPlease choose a rating between 1 and 5.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Menu", callback_data="main_menu")]])
                )
        else:
            await query.edit_message_text(
                "❌ <b>Invalid rating</b>\n\nPlease try again.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Menu", callback_data="main_menu")]])
            )
        return
    
    # Handle regenerate
    if data.startswith("regen_"):
        if not await force_join_check(update, context):
            return
        prompt = data.replace("regen_", "")
        try:
            await query.edit_message_text("🔄 <b>Regenerating response...</b>", parse_mode="HTML")
            resp = ai.chat(prompt, user_id)
            keyboard = [
                [InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen_{prompt[:30]}")],
                [InlineKeyboardButton("⭐ Rate", callback_data="rate_prompt")],
                [InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]
            ]
            await query.message.reply_text(
                resp,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Error: {str(e)}")
        return

# ============================================================================
# MESSAGE HANDLER
# ============================================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await save_user(user_id)
    
    if not await force_join_check(update, context):
        return
    
    allowed, msg = ai.check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    if context.user_data.get('broadcast_step') == 'media':
        if update.message.photo:
            photo = update.message.photo[-1]
            file = await photo.get_file()
            b = io.BytesIO()
            await file.download_to_memory(b)
            context.user_data['broadcast_image'] = b.getvalue()
            context.user_data['broadcast_step'] = 'caption'
            await update.message.reply_text("✅ <b>Image received! Send your caption.</b>", parse_mode="HTML")
        else:
            context.user_data['broadcast_image'] = None
            context.user_data['broadcast_step'] = 'caption'
            await update.message.reply_text(
                "📝 <b>Send caption text.</b>\n\n📌 To add buttons, use:\n<code>Text | URL</code> (one per line)",
                parse_mode="HTML"
            )
        return
    
    if context.user_data.get('broadcast_step') == 'caption' and update.message.text:
        text = update.message.text
        lines = text.split('\n')
        caption_lines, buttons = [], []
        for line in lines:
            if '|' in line and line.strip():
                parts = line.split('|')
                if len(parts) == 2:
                    buttons.append([InlineKeyboardButton(parts[0].strip(), url=parts[1].strip())])
                else:
                    caption_lines.append(line)
            else:
                caption_lines.append(line)
        context.user_data['broadcast_caption'] = '\n'.join(caption_lines)
        context.user_data['broadcast_buttons'] = buttons
        await update.message.reply_text(
            f"📢 <b>Preview</b>\n\n{context.user_data['broadcast_caption']}\n\nConfirm or cancel the broadcast:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="confirm_broadcast")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]
            ])
        )
        return
    
    msg = update.message.text
    if not msg:
        return
    
    try:
        await update.message.reply_chat_action("typing")
        resp = ai.chat(msg, user_id)
        
        keyboard = [
            [InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen_{msg[:30]}")],
            [InlineKeyboardButton("⭐ Rate", callback_data="rate_prompt")],
            [InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]
        ]
        
        if len(resp) > 4096:
            for i in range(0, len(resp), 4096):
                await update.message.reply_text(resp[i:i+4096], parse_mode="HTML")
        else:
            await update.message.reply_text(resp, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ============================================================================
# ERROR HANDLER
# ============================================================================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ============================================================================
# MAIN
# ============================================================================
def main():
    logger.info("🚀 Starting Nexus AI Bot with HTML formatting...")
    logger.info(f"📡 Health server: port {os.getenv('PORT', 10000)}")
    logger.info(f"💓 Keep-alive: {'✅ Enabled' if RENDER_EXTERNAL_URL else '❌ Disabled (set RENDER_EXTERNAL_URL)'}")
    logger.info(f"📢 Force join channels: {[c['username'] for c in REQUIRED_CHANNELS]}")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_history))
    
    for cmd in ["stats", "users", "broadcast"]:
        app.add_handler(CommandHandler(cmd, admin_commands))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    app.add_error_handler(error_handler)
    
    logger.info(f"✅ Bot is running with {len(ai.models)} models!")
    logger.info(f"📋 Available models: {list(ai.models.keys())}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()