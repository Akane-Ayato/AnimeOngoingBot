# AnimeOngoingBot

Telegram bot (Kurigram 2.2.26) that watches the Anikoto "recent anime" API and posts every new
episode on your channel with a 16:9 glass banner, a styled caption and a **Watch Now** button
that opens your site. Owner-controlled from Telegram, state in MongoDB, runs on Render, a VPS
or your own PC.

## Quick start

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # fill it in
python main.py
```

Needs Python 3.10+.

1. Create the bot with @BotFather, get `API_ID` / `API_HASH` from my.telegram.org.
2. Add the bot to your channel as **admin** with *Post messages*.
3. Put your numeric user id in `OWNER_ID` and press `/start` once so the bot can DM you alerts.
4. Fill `IMG` with comma separated image URLs for the `/start` and `/help` screens.

On the very first run the bot only **remembers** what is currently airing (no flood), then posts
new episodes only.

## Commands (all owner only except /start and /help)

| Command | What it does |
|---|---|
| `/start` | registers the user, sends a random `IMG` image + About / Help buttons |
| `/help` | help screen (owners also see the command list) |
| `/pause` · `/resume` | stop / start api checking and channel posting |
| `/check` | run one api check right now |
| `/status` | site, api, database, Telegram latency, posting state, RAM, CPU, storage, uptime, web URL |
| `/logs` | sends the complete log file (zipped if rotated) |
| `/post <url> [position]` | post one anime from any recent-anime style JSON page (1-based position) |
| `/batch_post <url> [force]` | post everything on that page one by one; skips already posted unless `force`; Stop button |
| `/set_int <seconds>` | api check interval (30 to 86400), applied immediately |
| `/post_design` | set the caption template: reply to a formatted message, or send it next. `reset` / `show` |
| `/set_sticker` | reply to a sticker; sent after every post. `reset` removes it |
| `/c_btn` | custom buttons under the main button. `clear` / `show`, `/cancel` aborts |
| `/restart` | re-executes the process; MongoDB settings are untouched |

### Post design placeholders
`{title} {episode} {language} {status} {description} {season} {year} {score} {genres} {studio}
{type} {aired} {total_eps} {id} {url} {channel} {powered_name} {powered_url}`

The synopsis is trimmed automatically so the caption always fits Telegram's 1024 limit.

### Custom buttons format
```
Button text 1 - http://example.com/
Btn 1 - http://x.com/ | Btn 2 - http://y.com/      (up to 3 per row)
Season 01 - SEASON 01                                (plain text = popup alert)
```

## How new episodes are detected

* `/recent-anime` is sorted by `updated_at`, so pages 1-2 are enough (`RECENT_PAGES`).
* Episode = `max(next_air_ep - 1, is_sub)`; language = *Dual* when `is_sub == is_dub`, else *Sub | E-Sub*.
* A post happens when that number is higher than the one stored in MongoDB.
* Before posting, `/series/{id}` must list that episode with an embed, so the button never opens an empty page. If it is not there yet the bot retries next cycle.
* Unknown shows are posted only when "Currently Airing"; unknown finished shows are recorded silently.
* If the upstream API fails the bot retries with backoff, then falls back to your site's `/api/recent`. Three failed checks in a row alert you.

## Fallbacks

banner + custom style + custom buttons -> banner + default style -> text post. Missing poster
uses `background_image`; if both fail the text post is used. Errors are logged to
`logs/bot.log` and DM'd to the owner (throttled).

## Hosting

* **Render**: push to GitHub, create a Blueprint from `render.yml`, fill the secret env vars. The
  bot serves `/health` and pings its own public URL every 10 minutes so the free tier stays awake.
  Render's disk is wiped on redeploy, which only affects logs; everything else lives in MongoDB.
* **VPS**: run with `systemd` or `pm2`/`screen`; `/restart` works under any supervisor.
* **Local**: `python main.py`. Set `WEB_SERVER=0` if you do not want the health port.

## Layout

```
main.py  config.py  render.yml  requirements.txt  .env.example
Database/mongodata.py
Plugins/start.py settings.py chnl_handler.py api_handler.py postmaker.py
        UI_design.py buttonhandler.py callbacks.py logger_error_handler.py
assets/logo.jpg  assets/fonts/ (Unbounded Bold, Inter Regular/SemiBold, OFL licensed)
```
(`logger&error_handler.py` is named `logger_error_handler.py` because `&` cannot be imported in Python.)
