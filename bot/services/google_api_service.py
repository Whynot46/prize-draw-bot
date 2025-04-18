import os
from googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials
from bot.config import Config
import httplib2
from bot.logger import logger
import bot.db as db
import json



try:
    creds_service = ServiceAccountCredentials.from_json_keyfile_name(
        Config.GOOGLE_CREDENTIALS_PATH, 
        scopes=Config.GOOGLE_SCOPES
    ).authorize(httplib2.Http())
    
    sheets_service = build('sheets', 'v4', http=creds_service)
except Exception as error:
    logger.error(f"Google API authentication error: {error}", exc_info=True)


async def update_users_sheet(users_data):
    """Обновляет данные пользователей в Google Sheets с актуальным количеством рефералов"""
    if not Config.GOOGLE_SHEETS_FILE_ID:
        return
        
    range_name = "Пользователи!A:D"  # Предполагаем формат: ID, Username, Name, Invited
    
    try:
        # Получаем текущие данные
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=Config.GOOGLE_SHEETS_FILE_ID,
            range=range_name
        ).execute()
        
        existing_data = result.get('values', [])
        existing_ids = {row[0] for row in existing_data[1:] if row}  # Пропускаем заголовок
        
        # Подготавливаем новые/обновленные данные
        updates = []
        for user in users_data:
            user_id = str(user['user_id'])
            invited = user.get('invited_friends', 0)
            
            if user_id in existing_ids:
                # Обновляем существующую запись
                for i, row in enumerate(existing_data[1:], start=1):
                    if row and row[0] == user_id:
                        # Обновляем только колонку с рефералами (индекс 3)
                        if len(row) < 4:
                            row.extend([''] * (4 - len(row)))
                        if str(row[3]) != str(invited):
                            updates.append({
                                'range': f"Пользователи!D{i+1}",
                                'values': [[invited]]
                            })
                        break
            else:
                # Добавляем нового пользователя
                updates.append({
                    'range': f"Пользователи!A{len(existing_data)+1}:D",
                    'values': [[
                        user_id,
                        user.get('username', ''),
                        user.get('fullname', ''),
                        invited
                    ]]
                })
        
        # Применяем обновления
        if updates:
            body = {
                'valueInputOption': 'RAW',
                'data': updates
            }
            sheets_service.spreadsheets().values().batchUpdate(
                spreadsheetId=Config.GOOGLE_SHEETS_FILE_ID,
                body=body
            ).execute()
            
    except Exception as e:
        logger.error(f"Error updating Google Sheet: {e}")


async def get_subscription_channels():
    """Получает список каналов для проверки подписки"""
    if not Config.GOOGLE_SHEETS_FILE_ID:
        return []
    
    range_name = "Каналы для подписки!A:C"  # ID | Название | Ссылка
    
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=Config.GOOGLE_SHEETS_FILE_ID,
            range=range_name
        ).execute()
        
        channels = []
        for row in result.get('values', [])[1:]:  # Пропускаем заголовок
            if not row or not row[0].lstrip('-').isdigit():
                continue
                
            channels.append({
                'channel_id': int(row[0]),
                'title': row[1] if len(row) > 1 else f"Канал {row[0]}",
                'link': row[2] if len(row) > 2 else None
            })
            
        return channels
        
    except Exception as e:
        logger.error(f"Ошибка получения каналов: {e}")
        return []


async def update_channels_sheet(channels_data):
    """Добавление данных каналов в Google Sheets"""
    if not Config.GOOGLE_SHEETS_FILE_ID:
        return
        
    range_name = "Каналы!A:C"
    
    existing_data = sheets_service.spreadsheets().values().get(
        spreadsheetId=Config.GOOGLE_SHEETS_FILE_ID,
        range=range_name
    ).execute().get('values', [])
    
    existing_ids = {row[0] for row in existing_data[1:] if row}
    
    new_channels = [
        [channel['channel_id'], 
         'Канал', 
         channel.get('name', '')]
        for channel in channels_data 
        if str(channel['channel_id']) not in existing_ids
    ]
    
    if new_channels:
        body = {'values': new_channels}
        sheets_service.spreadsheets().values().append(
            spreadsheetId=Config.GOOGLE_SHEETS_FILE_ID,
            range=range_name,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()


async def update_giveaways_sheet(giveaways_data):
    """Добавление данных розыгрышей в Google Sheets"""
    if not Config.GOOGLE_SHEETS_FILE_ID:
        return
        
    range_name = "Розыгрыши!A:H"
    
    existing_data = sheets_service.spreadsheets().values().get(
        spreadsheetId=Config.GOOGLE_SHEETS_FILE_ID,
        range=range_name
    ).execute().get('values', [])
    
    existing_ids = {row[0] for row in existing_data[1:] if row}
    
    new_giveaways = []
    for giveaway in giveaways_data:
        if str(giveaway['id']) in existing_ids:
            continue
            
        participants = await db.get_participants(giveaway['id'])
        winners = json.loads(giveaway['winners_ids']) if giveaway['winners_ids'] else []
        
        channel_info = await db.get_channel(giveaway['channel_id'])
        channel_name = channel_info[1] if channel_info else f"Канал {giveaway['channel_id']}"
        
        winners_names = []
        for winner_id in winners:
            user = await db.get_user_info(winner_id)
            if user:
                name = user.get('username', user.get('fullname', str(winner_id)))
                winners_names.append(f"@{name}" if user.get('username') else name)
        
        new_giveaways.append([
            giveaway['id'],                     # ID
            giveaway['name'],                  # Название
            giveaway['winners_count'],         # Кол-во победителей
            giveaway['announcement_date'],     # Дата и время завершения
            channel_name,                      # Название канала
            ", ".join([str(p) for p in participants]),  # ID участников
            len(participants),                 # Кол-во участников
            ", ".join(winners_names) if winners_names else "Нет победителей"  # Победители
        ])
    
    if new_giveaways:
        body = {'values': new_giveaways}
        sheets_service.spreadsheets().values().append(
            spreadsheetId=Config.GOOGLE_SHEETS_FILE_ID,
            range=range_name,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()


async def update_giveaway_stats():
    """Обновление всей статистики в Google Sheets"""
    if not Config.GOOGLE_SHEETS_FILE_ID:
        logger.error("GOOGLE_SHEETS_FILE_ID не определен!")
        return
    
    try:
        users = await db.get_all_users()
        channels = await db.get_all_channels()
        giveaways = await db.get_all_giveaways()
        
        await update_users_sheet(users)
        await update_channels_sheet(channels)
        await update_giveaways_sheet(giveaways)
    except Exception as e:
        logger.error(f"Error in update_giveaway_stats: {e}")
        raise