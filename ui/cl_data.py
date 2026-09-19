"""
ui/cl_data.py
Chainlit SQLAlchemy Data Layer integration for persistent conversation threads.
Points to the existing Neon PostgreSQL database without modifying application tables.
"""

import asyncio
import logging
import os
import ssl
from typing import Optional
import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()

logger = logging.getLogger(__name__)

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    "id" TEXT PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "createdAt" TEXT,
    "metadata" TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    "id" TEXT PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" TEXT,
    "userIdentifier" TEXT,
    "tags" TEXT[],
    "metadata" TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    "id" TEXT PRIMARY KEY,
    "name" TEXT,
    "type" TEXT,
    "threadId" TEXT NOT NULL,
    "parentId" TEXT,
    "disableFeedback" BOOLEAN,
    "streaming" BOOLEAN,
    "waitForAnswer" BOOLEAN,
    "isError" BOOLEAN,
    "metadata" TEXT,
    "tags" TEXT,
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" TEXT,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INT,
    "defaultOpen" BOOLEAN DEFAULT false,
    "autoCollapse" BOOLEAN DEFAULT false
);

CREATE TABLE IF NOT EXISTS elements (
    "id" TEXT PRIMARY KEY,
    "threadId" TEXT,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT,
    "display" TEXT,
    "size" TEXT,
    "language" TEXT,
    "autoPlay" BOOLEAN,
    "playerConfig" TEXT,
    "page" INT,
    "props" TEXT,
    "forId" TEXT,
    "mime" TEXT,
    "objectKey" TEXT
);

CREATE TABLE IF NOT EXISTS feedbacks (
    "id" TEXT PRIMARY KEY,
    "forId" TEXT NOT NULL,
    "threadId" TEXT,
    "value" INT NOT NULL,
    "comment" TEXT,
    "strategy" TEXT
);
"""

ALTER_TABLES_SQL = """
ALTER TABLE steps ADD COLUMN IF NOT EXISTS "defaultOpen" BOOLEAN DEFAULT false;
ALTER TABLE steps ADD COLUMN IF NOT EXISTS "autoCollapse" BOOLEAN DEFAULT false;
ALTER TABLE steps ADD COLUMN IF NOT EXISTS "showInput" TEXT;
ALTER TABLE steps ADD COLUMN IF NOT EXISTS "indent" INT;
ALTER TABLE steps ADD COLUMN IF NOT EXISTS "language" TEXT;
ALTER TABLE threads ADD COLUMN IF NOT EXISTS "tags" TEXT[];
"""


def get_db_async_url() -> str:
    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url:
        return ""
    clean = raw_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    clean = clean.replace("postgresql://", "postgresql+asyncpg://")
    # Strip any query parameters for asyncpg compatibility
    clean = clean.split("?")[0]
    return clean


async def init_chainlit_tables():
    """Ensure Chainlit thread and history tables exist in Neon DB."""
    async_url = get_db_async_url()
    if not async_url:
        logger.warning("No DATABASE_URL set; skipping Chainlit table init.")
        return

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        engine = create_async_engine(async_url, connect_args={"ssl": ssl_ctx})
        async with engine.begin() as conn:
            for stmt in CREATE_TABLES_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))
            for stmt in ALTER_TABLES_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        await conn.execute(text(stmt))
                    except Exception:
                        pass
        await engine.dispose()
        logger.info("Chainlit tables initialized successfully.")
    except Exception as exc:
        logger.warning("Error initializing Chainlit tables: %s", exc)


def get_data_layer() -> Optional[SQLAlchemyDataLayer]:
    """Factory returning configured SQLAlchemyDataLayer for Chainlit."""
    async_url = get_db_async_url()
    if not async_url:
        logger.warning("DATABASE_URL not found. Chainlit data layer disabled.")
        return None

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    return SQLAlchemyDataLayer(
        conninfo=async_url,
        connect_args={"ssl": ssl_ctx},
        ssl_require=True,
        show_logger=False,
    )
