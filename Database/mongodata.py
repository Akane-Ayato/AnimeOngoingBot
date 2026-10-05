"""
MongoDB layer (motor). Collections:
  users    - everyone who pressed /start
  posted   - one doc per anime: last posted episode (the dedupe memory)
  settings - single document with every runtime setting (survives /restart)
"""
import time
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient

import config

DEFAULT_SETTINGS = {
    "paused": False,
    "interval": config.DEFAULT_INTERVAL,
    "post_style": None,       # custom caption template (HTML) or None for the built-in default
    "sticker_id": None,       # file_id of the sticker sent after every post
    "c_btn_raw": None,        # raw text the owner sent for /c_btn (for display / editing)
    "c_btn_rows": [],         # parsed rows: [[{"text":..., "url":...} | {"text":..., "alert":key}]]
    "btn_alerts": {},         # popup texts keyed by short hash
    "seeded": False,          # first-run seeding finished
    "restart_notify": None,   # {"chat_id":..., "message_id":...} edited after /restart
}


class Database:
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.users = None
        self.posted = None
        self.settings = None
        self._cache: dict = {}

    async def connect(self):
        self.client = AsyncIOMotorClient(config.MONGO_URI, serverSelectionTimeoutMS=8000)
        self.db = self.client[config.DB_NAME]
        self.users = self.db["users"]
        self.posted = self.db["posted"]
        self.settings = self.db["settings"]
        await self.client.admin.command("ping")
        await self.posted.create_index("updated_at")
        doc = await self.settings.find_one({"_id": "config"}) or {}
        self._cache = {**DEFAULT_SETTINGS, **{k: v for k, v in doc.items() if k != "_id"}}
        # make sure every default key exists in the DB document
        await self.settings.update_one({"_id": "config"}, {"$setOnInsert": DEFAULT_SETTINGS}, upsert=True)

    async def close(self):
        if self.client:
            self.client.close()

    async def ping(self) -> Optional[float]:
        t = time.perf_counter()
        try:
            await self.client.admin.command("ping")
            return (time.perf_counter() - t) * 1000
        except Exception:
            return None

    # ---- settings (cached, write-through) ----
    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, DEFAULT_SETTINGS.get(key, default))

    async def set(self, key: str, value: Any):
        self._cache[key] = value
        await self.settings.update_one({"_id": "config"}, {"$set": {key: value}}, upsert=True)

    # ---- users ----
    async def add_user(self, user) -> bool:
        """Returns True when the user is new."""
        res = await self.users.update_one(
            {"_id": user.id},
            {
                "$set": {
                    "first_name": user.first_name,
                    "username": user.username,
                    "last_seen": int(time.time()),
                },
                "$setOnInsert": {"joined": int(time.time())},
            },
            upsert=True,
        )
        return res.upserted_id is not None

    async def count_users(self) -> int:
        return await self.users.count_documents({})

    # ---- posted memory ----
    async def get_posted(self, anime_id) -> Optional[dict]:
        return await self.posted.find_one({"_id": str(anime_id)})

    async def set_posted(self, anime_id, last_ep: int, title: str, message_id: Optional[int] = None, silent: bool = False):
        data = {"last_ep": last_ep, "title": title, "updated_at": int(time.time())}
        if message_id:
            data["message_id"] = message_id
        if silent:
            data["silent"] = True  # recorded without posting (seeding / finished shows)
        await self.posted.update_one({"_id": str(anime_id)}, {"$set": data}, upsert=True)

    async def count_posted(self) -> int:
        return await self.posted.count_documents({"silent": {"$ne": True}})

    async def count_known(self) -> int:
        return await self.posted.count_documents({})


db = Database()
