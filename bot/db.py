import aiosqlite
import json
from bot.config import Config
from bot.logger import logger


db_connection = None


async def init_db():
    global db_connection
    try:
        db_connection = await aiosqlite.connect(Config.DB_URL)
        # Создаем таблицы, если они не существуют
        await db_connection.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                fullname TEXT,
                role TEXT DEFAULT 'user',
                invited_friends INTEGER DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL
            )
        ''')
        await db_connection.execute('''
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                winners_count INTEGER NOT NULL,
                announcement_date TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                winners_ids TEXT DEFAULT '[]'
            )
        ''')
        await db_connection.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                giveaway_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY (giveaway_id, user_id),
                FOREIGN KEY (giveaway_id) REFERENCES giveaways(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        await db_connection.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                added_date TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db_connection.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise


async def add_user(user_id: int, username: str, fullname: str, referrer_id: int = None):
    """Добавляет пользователя с проверками"""
    try:
        async with db_connection.execute("BEGIN TRANSACTION"):
            # Проверяем, есть ли уже такой пользователь
            existing_user = await get_user_info(user_id)
            
            if existing_user:
                # Если пользователь уже есть, обновляем данные, но не меняем реферера
                await db_connection.execute(
                    "UPDATE users SET username = ?, fullname = ? WHERE user_id = ?",
                    (username, fullname, user_id)
                )
            else:
                # Нового пользователя добавляем с реферером (если он указан)
                await db_connection.execute(
                    "INSERT INTO users (user_id, username, fullname, referrer_id) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, username, fullname, referrer_id)
                )
            
            # Увеличиваем счетчик приглашенных у реферера
            if referrer_id and not await has_referral_bonus(user_id, referrer_id):
                await db_connection.execute(
                    "UPDATE users SET invited_friends = invited_friends + 1 "
                    "WHERE user_id = ?",
                    (referrer_id,)
                )
            
            await db_connection.commit()
        logger.info(f"User {user_id} added/updated successfully")
    except Exception as e:
        logger.error(f"Error in add_user for user {user_id}: {str(e)}")
        raise


async def create_giveaway(name: str, winners_count: int, announcement_date: str, channel_id: int):
    """Создает новый розыгрыш и возвращает его ID"""
    try:
        cursor = await db_connection.execute(
            "INSERT INTO giveaways (name, winners_count, announcement_date, channel_id) VALUES (?, ?, ?, ?) RETURNING id",
            (name, winners_count, announcement_date, channel_id)
        )
        giveaway_id = (await cursor.fetchone())[0]
        await db_connection.commit()
        logger.info(f"Giveaway {giveaway_id} created successfully")
        return giveaway_id
    except Exception as e:
        logger.error(f"Error in create_giveaway: {str(e)}")
        raise


async def add_participant(giveaway_id: int, user_id: int):
    try:
        await db_connection.execute(
            "INSERT OR IGNORE INTO participants (giveaway_id, user_id) VALUES (?, ?)",
            (giveaway_id, user_id)
        )
        await db_connection.commit()
        logger.info(f"User {user_id} added to giveaway {giveaway_id}")
    except Exception as e:
        logger.error(f"Error in add_participant: {str(e)}")
        raise


async def get_active_giveaways():
    """Возвращает список активных розыгрышей (дата окончания еще не наступила)"""
    try:
        cursor = await db_connection.execute(
            "SELECT id, name, channel_id FROM giveaways "
            "WHERE datetime(announcement_date) > datetime('now') "
            "ORDER BY announcement_date"
        )
        return await cursor.fetchall()
    except Exception as e:
        logger.error(f"Error in get_active_giveaways: {str(e)}")
        return []


async def get_giveaway_details(giveaway_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT * FROM giveaways WHERE id = ?", (giveaway_id,)
        )
        columns = [column[0] for column in cursor.description]
        result = await cursor.fetchone()
        return dict(zip(columns, result)) if result else None
    except Exception as e:
        logger.error(f"Error in get_giveaway_details for giveaway {giveaway_id}: {str(e)}")
        return None


async def get_participants(giveaway_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT user_id FROM participants WHERE giveaway_id = ?", 
            (giveaway_id,))
        return [row[0] for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error in get_participants for giveaway {giveaway_id}: {str(e)}")
        return []


async def set_winners(giveaway_id: int, winners_ids: list):
    try:
        await db_connection.execute(
            "UPDATE giveaways SET winners_ids = ? WHERE id = ?",
            (json.dumps(winners_ids), giveaway_id)
        )
        await db_connection.commit()
        logger.info(f"Winners set for giveaway {giveaway_id}")
    except Exception as e:
        logger.error(f"Error in set_winners for giveaway {giveaway_id}: {str(e)}")
        raise


async def get_invited_count(user_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT invited_friends FROM users WHERE user_id = ?", (user_id,)
        )
        result = await cursor.fetchone()
        return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error in get_invited_count for user {user_id}: {str(e)}")
        return 0


async def get_all_giveaways():
    try:
        cursor = await db_connection.execute("SELECT * FROM giveaways")
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error in get_all_giveaways: {str(e)}")
        return []


async def delete_giveaway(giveaway_id: int):
    """Удаляет розыгрыш и все связанные данные"""
    try:
        await db_connection.execute("BEGIN TRANSACTION")
        await db_connection.execute(
            "DELETE FROM participants WHERE giveaway_id = ?",
            (giveaway_id,)
        )
        await db_connection.execute(
            "DELETE FROM giveaways WHERE id = ?",
            (giveaway_id,)
        )
        await db_connection.commit()
        logger.info(f"Giveaway {giveaway_id} deleted successfully")
        return True
    except Exception as e:
        await db_connection.rollback()
        logger.error(f"Error in delete_giveaway for giveaway {giveaway_id}: {str(e)}")
        return False


async def get_user_info(user_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT user_id, username, fullname, invited_friends FROM users WHERE user_id = ?", 
            (user_id,)
        )
        result = await cursor.fetchone()
        if result:
            return {
                'user_id': result[0],
                'username': result[1],
                'fullname': result[2],
                'invited_friends': result[3] or 0
            }
        return None
    except Exception as e:
        logger.error(f"Error in get_user_info for user {user_id}: {str(e)}")
        return None


async def get_all_users():
    try:
        cursor = await db_connection.execute("SELECT * FROM users")
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error in get_all_users: {str(e)}")
        return []


async def get_all_channels():
    try:
        cursor = await db_connection.execute(
            "SELECT channel_id, title, added_date FROM channels"
        )
        return [{
            'channel_id': row[0],
            'name': row[1],
            'added_date': row[2]
        } for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error in get_all_channels: {str(e)}")
        return []


async def get_user_by_id(user_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        columns = [column[0] for column in cursor.description]
        result = await cursor.fetchone()
        return dict(zip(columns, result)) if result else None
    except Exception as e:
        logger.error(f"Error in get_user_by_id for user {user_id}: {str(e)}")
        return None


async def get_giveaways_by_channel(channel_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT * FROM giveaways WHERE channel_id = ?", (channel_id,)
        )
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error in get_giveaways_by_channel for channel {channel_id}: {str(e)}")
        return []


async def add_channel(channel_id: int, title: str):
    try:
        await db_connection.execute(
            "INSERT OR REPLACE INTO channels (channel_id, title) VALUES (?, ?)",
            (channel_id, title)
        )
        await db_connection.commit()
        logger.info(f"Channel {channel_id} added successfully")
    except Exception as e:
        logger.error(f"Error in add_channel for channel {channel_id}: {str(e)}")
        raise


async def get_channel(channel_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT channel_id, title FROM channels WHERE channel_id = ?",
            (channel_id,)
        )
        return await cursor.fetchone()
    except Exception as e:
        logger.error(f"Error in get_channel for channel {channel_id}: {str(e)}")
        return None


async def get_giveaway_status(giveaway_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT winners_ids, announcement_date FROM giveaways WHERE id = ?", 
            (giveaway_id,)
        )
        result = await cursor.fetchone()
        return {
            'winners_ids': json.loads(result[0]) if result[0] else [],
            'announcement_date': result[1]
        } if result else None
    except Exception as e:
        logger.error(f"Error in get_giveaway_status for giveaway {giveaway_id}: {str(e)}")
        return None


async def is_participant(giveaway_id: int, user_id: int) -> bool:
    try:
        cursor = await db_connection.execute(
            "SELECT 1 FROM participants WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id)
        )
        return await cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error in is_participant for user {user_id} in giveaway {giveaway_id}: {str(e)}")
        return False


async def get_user_referral_status(user_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT referrer_id FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = await cursor.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error in get_user_referral_status for user {user_id}: {str(e)}")
        return None


async def has_referral_bonus(user_id: int, referrer_id: int) -> bool:
    try:
        cursor = await db_connection.execute(
            "SELECT 1 FROM users WHERE user_id = ? AND referrer_id = ?",
            (user_id, referrer_id)
        )
        return await cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error in has_referral_bonus for user {user_id} and referrer {referrer_id}: {str(e)}")
        return False


async def update_user_invited_count(user_id: int, new_count: int):
    try:
        await db_connection.execute(
            "UPDATE users SET invited_friends = ? WHERE user_id = ?",
            (new_count, user_id)
        )
        await db_connection.commit()
        logger.info(f"Updated invited count for user {user_id} to {new_count}")
    except Exception as e:
        logger.error(f"Error in update_user_invited_count for user {user_id}: {str(e)}")
        raise


async def get_user_referrals(user_id: int):
    try:
        cursor = await db_connection.execute(
            "SELECT user_id FROM users WHERE referrer_id = ?",
            (user_id,)
        )
        return [row[0] for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error in get_user_referrals for user {user_id}: {str(e)}")
        return []
    

async def get_connected_channels():
    cursor = await db_connection.execute(
        "SELECT channel_id, title FROM channels"  # Теперь возвращаем и ID, и название
    )
    return await cursor.fetchall()  # Возвращаем список кортежей (channel_id, title)