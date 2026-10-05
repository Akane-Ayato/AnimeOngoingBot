<p align="center">
  <img src="assets/logo.jpg" alt="Anime Ongoing Bot" width="220">
</p>

<h1 align="center">Anime Ongoing Bot</h1>

<p align="center">
  A fast, owner-controlled Telegram bot that watches the Anikoto API and posts every new ongoing anime
  episode on your channel — with a glass banner, a styled caption and a Watch Now button that opens your site.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/engine-Kurigram%202.2.26-2CA5E0" alt="kurigram">
  <img src="https://img.shields.io/badge/database-MongoDB-47A248" alt="mongodb">
  <img src="https://img.shields.io/badge/host-Render%20%7C%20VPS%20%7C%20Local-8A2BE2" alt="hosting">
</p>

---

## ✨ Features

- **Automatic posting** — checks the API on a timer, detects new episodes, and posts each one exactly once. Progress is stored in MongoDB, so restarts never cause duplicates.
- **Smart episode logic** — episode = `max(next_air_ep − 1, is_sub)`; language shows **Dual** when sub and dub are equal, otherwise **Sub | E-Sub**.
- **Embed verification** — before posting, the bot confirms the episode really has a playable embed on `/series/{id}`, so the Watch Now button never opens an empty page. Not ready yet? It retries next cycle.
- **Banner maker** — a 16:9 glassmorphism banner built from the API poster: poster card, title, channel logo + name and a short description.
- **Post designer** — replace the default caption with your own template using placeholders (`{title}`, `{episode}`, `{status}` …). The synopsis auto-trims to fit Telegram's caption limit.
- **Button maker** — add custom button rows under the main button, including popup-alert buttons that need no link.
- **Custom sticker** — send a sticker after every anime post.
- **Manual posting** — `/post` one anime or `/batch_post` a whole JSON page, with a Stop button.
- **Pause / resume / interval** — control the checker from Telegram; every setting lives in MongoDB and survives `/restart`.
- **Fallbacks everywhere** — API retries with backoff, then your site's own `/api` proxy; banner → default style → text-only post; missing poster uses the background image.
- **Error alerts** — crashes, API outages, channel-permission problems and post fallbacks are DM'd to you (throttled) and written to a rotating log file.
- **Live status** — site, API, database and Telegram latency, posting state, RAM, CPU, storage, uptime and web URL in one message.
- **Production-ready** — async MongoDB, shared HTTP session, a `/health` endpoint with Render keep-alive, clean shutdown and a self-restart command.
- **Small-caps UI** — text symbols only, no emoji, in every bot message.

## 🤖 Commands

| Command | Description |
|---|---|
| `/start` | Register and open the start screen (random image + About / Help buttons) |
| `/help` | Help screen *(owners also see the command list)* |
| `/pause` | Stop API checking and channel posting *(owner)* |
| `/resume` | Start checking again, runs a check immediately *(owner)* |
| `/check` | Run one API check right now *(owner)* |
| `/status` | Site, API, database and bot health *(owner)* |
| `/logs` | Receive the complete log file *(owner)* |
| `/post <url> [position]` | Post one anime from any recent-anime JSON page; position starts at 1 *(owner)* |
| `/batch_post <url> [force]` | Post every anime on that page one by one; already posted ones are skipped unless `force` *(owner)* |
| `/set_int <seconds>` | Set the API check interval, 30–86400 s *(owner)* |
| `/post_design` | Set the caption template — reply to a formatted message, or send it next. `reset` / `show` *(owner)* |
| `/set_sticker` | Set the post sticker — reply to a sticker. `reset` removes it *(owner)* |
| `/c_btn` | Set custom buttons for every post. `clear` / `show` *(owner)* |
| `/cancel` | Cancel a pending `/c_btn` or `/post_design` prompt *(owner)* |
| `/restart` | Restart the bot process; MongoDB settings are untouched *(owner)* |

### Post design placeholders

```
{title} {episode} {language} {status} {description} {season} {year} {score}
{genres} {studio} {type} {aired} {total_eps} {id} {url} {channel}
{powered_name} {powered_url}
```

### Custom button format

```
Button text 1 - http://example.com/
Btn 1 - http://x.com/ | Btn 2 - http://y.com/        (up to 3 per row)
Season 01 - SEASON 01                                  (plain text = popup alert)
480p - https://xxx | 720p - https://xxx
```

The post keyboard is always `[ ▷ Watch Now ]` first, then your custom rows. With no custom buttons, only Watch Now is shown.

## 🛠 Setup

### 1. Requirements

- Python 3.10+
- A Telegram **bot token** ([@BotFather](https://t.me/BotFather))
- Telegram **API ID / API Hash** ([my.telegram.org](https://my.telegram.org))
- A **MongoDB** connection string ([MongoDB Atlas](https://www.mongodb.com/atlas) free tier works fine)
- Your channel, with the bot added as **admin** with *Post messages*

### 2. Install

```bash
git clone <your-repo-url>
cd AnimeOngoingBot
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

> `tgcrypto` in `requirements.txt` is an optional speed-up. Remove that line if your host can't build it.

### 3. Configure

Set these in `.env` (or as platform environment variables). Never commit real values.

| Variable | Required | Description |
|---|---|---|
| `API_ID` | ✅ | Telegram API ID |
| `API_HASH` | ✅ | Telegram API hash |
| `BOT_TOKEN` | ✅ | Bot token from BotFather |
| `OWNER_ID` | ✅ | Your user ID (comma separated for several owners). Press `/start` once so the bot can DM you |
| `CHANNEL_ID` | ✅ | Channel `@username` or numeric id (`-100…`) |
| `MONGO_URI` | ✅ | MongoDB connection string |
| `DB_NAME` | – | Database name (default `AnimeOngoingBot`) |
| `LOG_CHANNEL` | – | Extra chat for error alerts |
| `SITE_URL` | – | Your site (default `https://ani-void-tv.vercel.app`) |
| `API_BASE` | – | Upstream API (default `https://anikotoapi.site`) |
| `USE_SITE_FALLBACK` | – | Fall back to `SITE_URL/api` if upstream fails (default `1`) |
| `DEFAULT_INTERVAL` | – | Check interval in seconds (default `300`, changeable with `/set_int`) |
| `RECENT_PAGES` | – | API pages scanned per check (default `2`) |
| `PER_PAGE` | – | Items per page (default `40`) |
| `POST_DELAY` | – | Seconds between channel posts (default `5`) |
| `CHANNEL_NAME` | – | Name drawn on banners (default `Aɳιɱҽ Oɳɠσιɳɠ`) |
| `POWERED_BY_NAME` / `POWERED_BY_URL` | – | The "Powered By" link in posts |
| `IMG` | – | Comma separated image URLs; one is picked at random for `/start` and `/help` |
| `PORT` | – | Health-check web server port (default `8080`; Render sets it) |
| `WEB_SERVER` | – | `0` disables the health server |
| `PUBLIC_URL` / `KEEP_ALIVE` | – | Self-ping to keep Render's free tier awake (auto on Render) |

### 4. Run

```bash
python main.py
```

On the very first run the bot only **remembers** the shows that are airing right now (so your channel isn't flooded), then posts new episodes only.

## ☁️ Hosting

- **Render** — push the repo to GitHub, create a Blueprint from `render.yml`, fill in the secret variables. The bot serves `/health` and pings its own public URL every 10 minutes. Render's disk resets on redeploy, which only affects logs — everything else is in MongoDB.
- **VPS** — run under `systemd`, `pm2` or `screen`. `/restart` works under any supervisor.
- **Local** — `python main.py`. Set `WEB_SERVER=0` if you don't want the health port.

## 🔄 How a new episode is detected

1. The poller reads `/recent-anime` (sorted by `updated_at`, newest first) every interval.
2. Each show's episode number is compared with the last one stored in MongoDB.
3. A higher number triggers verification: `/series/{id}` must list that episode with an embed.
4. The banner, caption and buttons are built and posted, then the sticker (if set) follows.
5. The new episode number is saved, so the same episode is never posted twice.

Unknown shows are posted only when *Currently Airing*; unknown finished shows are recorded silently so old titles with metadata edits don't spam the channel.

## 📁 Project Structure

```
.
├── main.py                      # entry point: DB, web server, client, poller
├── config.py                    # environment config + owner filter
├── render.yml                   # Render blueprint
├── requirements.txt
├── .env.example
├── Database/
│   └── mongodata.py             # MongoDB layer (users, posted, settings)
├── Plugins/
│   ├── start.py                 # /start, /help
│   ├── settings.py              # pause, resume, set_int, sticker, post_design, status, restart
│   ├── chnl_handler.py          # posting engine, poller, /check, /post, /batch_post
│   ├── api_handler.py           # API fetching, retries, episode logic, health checks
│   ├── postmaker.py             # caption values + Pillow banner
│   ├── UI_design.py             # small caps, default style, all bot texts
│   ├── buttonhandler.py         # button parser/builder, /c_btn, prompt capture
│   ├── callbacks.py             # inline button callbacks
│   └── logger_error_handler.py  # logging, error alerts, /logs
└── assets/
    ├── logo.jpg
    └── fonts/                   # Unbounded Bold, Inter Regular/SemiBold (OFL)
```

## 🗄 Data Stored in MongoDB

| Collection | Purpose |
|---|---|
| `users` | Everyone who pressed `/start` |
| `posted` | Last posted episode per anime — the duplicate-protection memory |
| `settings` | Paused state, interval, post style, sticker, custom buttons, seeding flag |

## 🧰 Troubleshooting

| Problem | Fix |
|---|---|
| `USER_NOT_PARTICIPANT` / "Channel check failed" at startup | Add the bot to the channel as admin with *Post messages* |
| No error alerts arrive | Press `/start` on the bot once from your owner account |
| Posts appear without a banner | Check `/logs` — the poster could not be downloaded, so the text-only fallback was used |
| Nothing posts after a restart | Check `/status` — posting may be paused; use `/resume` |

## ⚠️ Security

Never commit real values for `BOT_TOKEN`, `API_HASH` or `MONGO_URI`. If any of them were ever exposed, rotate them immediately:
- Revoke & regenerate the bot token in [@BotFather](https://t.me/BotFather)
- Change the MongoDB user's password in Atlas

## 🙌 Credits

Powered by [Anime Void](https://t.me/Index_void) · Built with [Kurigram](https://github.com/KurimuzonAkuma/kurigram) and Pillow
