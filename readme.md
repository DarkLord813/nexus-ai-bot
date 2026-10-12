# Nexus AI Bot 🤖

A powerful Telegram bot with multi-model AI support, featuring Groq, DeepSeek, and GPT-OSS models with DeepSeek-style formatting.

---

## ✨ Features

- **Multi-Model Support**: Switch between Groq (Llama 3.3 70B, Llama 3.1 8B, Mixtral 8x7B), DeepSeek V3.1, and GPT-OSS 120B
- **DeepSeek-Style Formatting**: Clean, structured responses with proper HTML formatting
- **Interactive Rating System**: Rate responses with 5-star system
- **Chat History**: View and clear conversation history
- **Force Join System**: Users must join required channels to use the bot
- **Rate Limiting**: Prevents spam with cooldown and message limits
- **Admin Panel**: Statistics, user management, and broadcast system
- **Automatic Fallback**: If Groq limit is reached, automatically switches to Drift AI models
- **Health Server**: Built-in health check for deployment platforms like Render
- **Keep-Alive Ping**: Automatic self-ping every 5 minutes to prevent bot from sleeping (24/7 uptime)

---

## 📋 Prerequisites

- Python 3.9+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- Groq API Key ([Groq Console](https://console.groq.com))
- (Optional) Drift API for DeepSeek and GPT models

---

## 🚀 Installation

### 1. Clone the repository
```bash
git clone https://github.com/DarkLord813/nexus-ai-bot.git
cd nexus-ai-bot