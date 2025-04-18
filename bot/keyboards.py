from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
import bot.db as db
import json


async def get_main_menu_keyboard(is_admin: bool = False):
    if is_admin:
        buttons = [
            [KeyboardButton(text="Создать розыгрыш")],
            [KeyboardButton(text="Все розыгрыши")],
            [KeyboardButton(text="Подключенные каналы")],
            [KeyboardButton(text="Сделать рассылку")]  
        ]
    else:
        buttons = [
            [KeyboardButton(text="Список активных розыгрышей")],
            [KeyboardButton(text="Приведи друга")]
        ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


async def get_giveaways_list_keyboard(giveaways):
    if not giveaways:
        return None
    
    inline_keyboard = []
    for giveaway in giveaways:
        inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{giveaway[1]}",
                callback_data=f"participate_{giveaway[0]}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


async def get_referral_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Скопировать ссылку",
            callback_data=f"copy_ref_{user_id}"
        )
    ]])


async def get_giveaway_management_keyboard(giveaway_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Определить победителей",
                callback_data=f"select_winners_{giveaway_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Удалить розыгрыш",
                callback_data=f"delete_giveaway_{giveaway_id}"
            )
        ]
    ])
    

async def get_channels_list_keyboard(channels):
    inline_keyboard = []
    for channel_id in channels:
        inline_keyboard.append([
            InlineKeyboardButton(
                text=f"Канал {channel_id}",
                url=f"https://t.me/{channel_id}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


async def get_channels_selection_keyboard(channels, selected_channels=None):
    """Клавиатура для выбора каналов с отметкой выбранных"""
    if selected_channels is None:
        selected_channels = []
    
    inline_keyboard = []
    for channel in channels:
        channel_id, title = channel[0], channel[1]
        is_selected = channel_id in selected_channels
        prefix = "✅ " if is_selected else ""
        
        inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{prefix}{title}",
                callback_data=f"toggle_channel_{channel_id}"
            )
        ])
    
    # Кнопка сохранения (активна только если есть выбранные каналы)
    if selected_channels:
        inline_keyboard.append([
            InlineKeyboardButton(
                text="💾 Сохранить выбор",
                callback_data="save_channels"
            )
        ])
    else:
        inline_keyboard.append([
            InlineKeyboardButton(
                text="❌ Выберите хотя бы один канал",
                callback_data="no_channels_selected"
            )
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


async def get_winners_selection_keyboard(giveaway_id, participants, page=0):
    items_per_page = 10
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    paginated_participants = participants[start_idx:end_idx]
    
    giveaway = await db.get_giveaway_details(giveaway_id)
    if not giveaway:
        return InlineKeyboardMarkup(inline_keyboard=[])
    
    current_winners = json.loads(giveaway['winners_ids']) if giveaway['winners_ids'] else []
    
    inline_keyboard = []
    for user_id in paginated_participants:
        user = await db.get_user_info(user_id)
        if not user:
            continue
            
        display_name = f"@{user['username']}" if user['username'] else user['fullname']
        if user_id in current_winners:
            display_name = "✅ " + display_name
            
        inline_keyboard.append([
            InlineKeyboardButton(
                text=display_name,
                callback_data=f"winner_{giveaway_id}_{user_id}_{page}"
            )
        ])
    
    # Добавляем пагинацию если нужно
    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"winners_page_{giveaway_id}_{page-1}"
            )
        )
    
    if end_idx < len(participants):
        navigation_buttons.append(
            InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=f"winners_page_{giveaway_id}_{page+1}"
            )
        )
    
    if navigation_buttons:
        inline_keyboard.append(navigation_buttons)
    
    # Кнопки сохранения и отмены
    inline_keyboard.append([
        InlineKeyboardButton(
            text=f"Сохранить ({len(current_winners)}/{giveaway['winners_count']})",
            callback_data=f"save_winners_{giveaway_id}"
        ),
        InlineKeyboardButton(
            text="Назад",
            callback_data=f"cancel_winners_{giveaway_id}"
        )
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


async def get_participate_keyboard(giveaway_id):
    participate_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Участвовать",
            callback_data=f"participate_{giveaway_id}"
        )]
    ])
    return participate_button


async def get_subscription_check_keyboard(channels):
    """Создает кнопки для подписки с приоритетом: ссылка из таблицы -> fallback к ID"""
    buttons = []
    for channel in channels:
        # Используем ссылку из таблицы или создаем из ID
        url = channel.get('link') or f"https://t.me/c/{str(abs(channel['channel_id']))}"
        
        buttons.append([
            InlineKeyboardButton(
                text=f"Подписаться на {channel['title']}", 
                url=url
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(
            text="✅ Я подписался", 
            callback_data="check_subscriptions"
        )
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_broadcast_media_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Прикрепить указанные фото", callback_data="confirm_photos")],
        [InlineKeyboardButton(text="Не прикреплять фото", callback_data="no_photos")],
        [InlineKeyboardButton(text="Отменить рассылку", callback_data="cancel_broadcast")]
    ])


async def get_broadcast_confirmation_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить рассылку", callback_data="approve_broadcast")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_broadcast")]
    ])


async def get_broadcast_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Прикрепить фото")],
            [KeyboardButton(text="Пропустить прикрепление фото")],
            [KeyboardButton(text="Отменить рассылку")]
        ],
        resize_keyboard=True
    )


async def get_broadcast_confirmation_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Подтвердить рассылку")],
            [KeyboardButton(text="Отменить рассылку")]
        ],
        resize_keyboard=True
    )


async def get_giveaway_confirmation_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_giveaway"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_giveaway")
        ]
    ])


async def remove_keyboard():
    return ReplyKeyboardRemove()