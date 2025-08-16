# Local AI News Bot

This project is a Discord bot that fetches recent AI articles, summarizes them using a local LLM via [LM Studio](https://lmstudio.ai/), and publishes approved articles to a public Discord channel.

## Requirements

- Python 3.10+
- A Discord bot token
- A NewsAPI key ([sign up at newsapi.org](https://newsapi.org/))
- An installation of [LM Studio](https://lmstudio.ai/) running locally

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/LiamFearon/LocalAINews.git
   cd LocalAINews
   ```

2. **Create a virtual environment and install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate   # macOS/Linux
   venv\\Scripts\\activate    # Windows

   pip install -r requirements.txt
   ```

3. **Configure LM Studio**
   - Install LM Studio and download a suitable model (e.g. `qwen2.5-7b-instruct-mlx`).
   - Run LM Studio with its API server enabled. By default, it listens at `http://127.0.0.1:1234`.
   - Note the URL and model name, as you will need them for `.env`.

4. **Create your `.env` file**
   Copy the example file and update it with your own values:
   ```bash
   cp .env.example .env
   ```
   Fill in:
   - `DISCORD_TOKEN` – your Discord bot token
   - `NEWS_API_KEY` – your NewsAPI key
   - `ADMIN_CHANNEL_ID` – ID of the Discord channel where drafts should appear
   - `POST_CHANNEL_ID` – ID of the public channel for approved posts
   - `LMSTUDIO_BASE_URL` – e.g. `http://127.0.0.1:1234`
   - `LMSTUDIO_MODEL` – the model name as configured in LM Studio
   - `LMSTUDIO_API_KEY` – leave blank unless your LM Studio instance requires one

   Example:
   ```dotenv
   DISCORD_TOKEN=your-bot-token
   NEWS_API_KEY=your-newsapi-key
   ADMIN_CHANNEL_ID=123456789012345678
   POST_CHANNEL_ID=234567890123456789
   LMSTUDIO_BASE_URL=http://127.0.0.1:1234
   LMSTUDIO_MODEL=qwen2.5-7b-instruct-mlx
   LMSTUDIO_API_KEY=
   LMSTUDIO_TIMEOUT_SECS=120
   LM_USE_TOOLS=0
   ```

5. **Run the bot**
   ```bash
   python main.py
   ```

## How it works

1. Topics are defined in `topics.txt`.
2. The bot fetches articles using NewsAPI.
3. Each article is summarized using LM Studio.
4. Drafts are posted to the admin channel for review.
5. Approved items are published to the public channel as rich embeds.
