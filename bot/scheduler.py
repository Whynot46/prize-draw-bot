import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import bot.db as db
import bot.services.google_api_service as google_api
from aiogram import Bot
import random
import json
from apscheduler.triggers.date import DateTrigger
from bot.logger import logger


scheduler = AsyncIOScheduler()


async def announce_giveaway_results(bot: Bot, giveaway_id: int):
    try:
        giveaway = await db.get_giveaway_details(giveaway_id)
        if not giveaway:
            logger.warning(f"Giveaway {giveaway_id} not found for announcement")
            return

        # Получаем текущих победителей (если есть)
        current_winners = json.loads(giveaway['winners_ids']) if giveaway['winners_ids'] else []
        
        # Получаем всех участников
        participants = await db.get_participants(giveaway_id)
        
        # Если нужно добавить еще победителей
        if len(current_winners) < giveaway['winners_count']:
            remaining_winners_count = giveaway['winners_count'] - len(current_winners)
            remaining_participants = [p for p in participants if p not in current_winners]
            
            # Выбираем дополнительных победителей
            new_winners = await select_winners(remaining_participants, remaining_winners_count)
            current_winners.extend(new_winners)
            
            # Сохраняем обновленный список победителей
            await db.set_winners(giveaway_id, current_winners)
        
        # Формируем и отправляем сообщение с победителями
        await send_winners_announcement(bot, giveaway, current_winners)
        
        # Обновляем данные в Google Sheets
        await google_api.update_giveaway_stats()
        
        # Удаляем розыгрыш после завершения
        await db.delete_giveaway(giveaway_id)
        logger.info(f"Giveaway {giveaway_id} results announced successfully")
    except Exception as e:
        logger.error(f"Error in announce_giveaway_results for giveaway {giveaway_id}: {str(e)}")


async def restore_scheduled_giveaways(bot: Bot):
    """Восстановление запланированных розыгрышей при перезапуске бота"""
    try:
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor = await db.db_connection.execute(
            "SELECT id, announcement_date FROM giveaways "
            "WHERE datetime(announcement_date) > datetime(?)",
            (now,)
        )
        active_giveaways = await cursor.fetchall()

        for giveaway_id, announcement_date in active_giveaways:
            try:
                announcement_datetime = datetime.strptime(announcement_date, "%Y-%m-%d %H:%M:%S")
                scheduler.add_job(
                    announce_giveaway_results,
                    trigger=DateTrigger(announcement_datetime),
                    args=[bot, giveaway_id],
                    id=f"giveaway_{giveaway_id}"
                )
                logger.info(f"Restored scheduled giveaway {giveaway_id}")
            except Exception as e:
                logger.error(f"Error restoring giveaway {giveaway_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Error in restore_scheduled_giveaways: {str(e)}")


async def setup_scheduler(bot: Bot):
    """Настройка планировщика"""
    try:
        scheduler.add_job(hourly_update, 'interval', hours=1)
        scheduler.start()
        await restore_scheduled_giveaways(bot)
        logger.info("Scheduler setup completed successfully")
    except Exception as e:
        logger.error(f"Error in setup_scheduler: {str(e)}")
        raise


async def hourly_update():
    """Ежечасное обновление данных в Google Sheets"""
    try:
        await google_api.update_giveaway_stats()
        logger.info("Hourly update completed successfully")
    except Exception as e:
        logger.error(f"Error in hourly_update: {str(e)}")


async def select_winners(participants: list, winners_count: int) -> list:
    """
    Выбирает победителей с учетом реферальной системы
    :param participants: список ID участников
    :param winners_count: количество победителей
    :return: список ID победителей
    """
    try:
        if not participants:
            logger.warning("No participants to select winners from")
            return []
        
        # Если победителей должно быть больше чем участников
        if winners_count >= len(participants):
            logger.info(f"All participants ({len(participants)}) selected as winners")
            return participants.copy()
        
        # Создаем взвешенный список участников
        weighted_participants = []
        for user_id in participants:
            user = await db.get_user_info(user_id)
            if not user:
                continue
            
            # Базовый вес (1 за участие)
            weight = 1
            # Добавляем вес за приглашенных друзей
            weight += user.get('invited_friends', 0)
            
            # Добавляем пользователя в список N раз, где N - его вес
            weighted_participants.extend([user_id] * weight)
        
        # Если после взвешивания список пуст
        if not weighted_participants:
            logger.warning("Weighted participants list is empty, using random selection")
            return random.sample(participants, min(winners_count, len(participants)))
        
        winners = []
        for _ in range(winners_count):
            if not weighted_participants:
                break
            
            # Выбираем случайного победителя
            winner = random.choice(weighted_participants)
            winners.append(winner)
            
            # Удаляем все вхождения этого пользователя из списка
            weighted_participants = [uid for uid in weighted_participants if uid != winner]
        
        logger.info(f"Selected {len(winners)} winners from {len(participants)} participants")
        return winners
    except Exception as e:
        logger.error(f"Error in select_winners: {str(e)}")
        return random.sample(participants, min(winners_count, len(participants)))


async def send_winners_announcement(bot: Bot, giveaway: dict, winners: list):
    """Отправляет сообщение с победителями"""
    try:
        if not winners:
            message = f"🏆 Розыгрыш '{giveaway['name']}' завершен!\n\nК сожалению, не было участников."
        else:
            winners_info = []
            for winner_id in winners:
                user = await db.get_user_info(winner_id)
                name = f"@{user['username']}" if user and user.get('username') else f"ID:{winner_id}"
                winners_info.append(name)
            
            message = (
                f"🏆 Розыгрыш '{giveaway['name']}' завершен!\n\n"
                f"Победители:\n" + "\n".join(winners_info) + "\n\nПоздравляем!"
            )
        
        await bot.send_message(giveaway['channel_id'], message)
        logger.info(f"Winners announcement sent to channel {giveaway['channel_id']}")
    except Exception as e:
        logger.error(f"Error in send_winners_announcement: {str(e)}")