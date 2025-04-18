from aiogram.filters.command import Command
from aiogram import F, Bot
from aiogram.types import Message
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types.callback_query import CallbackQuery
from aiogram.filters import StateFilter
import bot.keyboards as kb
import bot.db as db
from bot.states import *
from bot.config import Config, is_admin
import json
import bot.services.google_api_service as google_api_service
from bot.scheduler import scheduler, announce_giveaway_results
from apscheduler.triggers.date import DateTrigger
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from asyncio import sleep
from bot.logger import logger


router = Router()


@router.message(Command("start"), F.chat.type.in_({"group", "supergroup", "channel"}))
async def add_channel_handler(message: Message, bot: Bot):
    """Обработчик добавления нового канала/группы"""
    try:
        if not is_admin(message.from_user.id):
            logger.warning(f"Non-admin user {message.from_user.id} tried to add channel")
            return await message.answer("Только администраторы могут добавлять каналы.")
        
        chat_id = message.chat.id
        chat_title = message.chat.title
        
        # Проверяем, что бот является администратором
        try:
            chat_member = await bot.get_chat_member(chat_id, bot.id)
            if chat_member.status not in ["administrator", "creator"]:
                logger.warning(f"Bot is not admin in channel {chat_id}")
                return await message.answer("Бот должен быть администратором в этом чате.")
        except Exception as e:
            logger.error(f"Error checking bot admin rights in channel {chat_id}: {str(e)}")
            return await message.answer(f"Ошибка проверки прав: {str(e)}")
        
        # Добавляем канал в БД
        try:
            await db.add_channel(chat_id, chat_title)
            
            # Отправляем сообщение в канал
            try:
                await bot.send_message(
                    chat_id,
                    f"🎉 Этот канал теперь подключен к боту розыгрышей!\n"
                    f"Администраторы могут создавать здесь розыгрыши."
                )
            except Exception as e:
                logger.error(f"Error sending welcome message to channel {chat_id}: {str(e)}")
            
            await google_api_service.update_giveaway_stats()
            logger.info(f"Channel {chat_id} added successfully")
        except Exception as e:
            logger.error(f"Error adding channel {chat_id}: {str(e)}")
            await message.answer("Произошла ошибка при добавлении канала.")
    except Exception as e:
        logger.error(f"Error in add_channel_handler: {str(e)}")
        await message.answer("Произошла ошибка при обработке запроса.")


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext, bot: Bot):
    try:
        user_id = message.from_user.id
        referrer_id = None
        
        # Обрабатываем реферальную ссылку
        if len(message.text.split()) > 1:
            try:
                referrer_id = int(message.text.split()[1].strip())
                
                # Проверка 1: пользователь не перешел по своей же ссылке
                if referrer_id == user_id:
                    logger.warning(f"User {user_id} tried to use own referral link")
                    await message.answer("Нельзя использовать свою же реферальную ссылку!")
                    referrer_id = None
                
                # Проверка 2: реферер существует
                elif not await db.get_user_info(referrer_id):
                    logger.warning(f"Invalid referral link for user {user_id}")
                    await message.answer("Недействительная реферальная ссылка")
                    referrer_id = None
                    
                # Проверка 3: пользователь еще не был зарегистрирован
                elif await db.get_user_info(user_id):
                    logger.warning(f"User {user_id} already registered")
                    await message.answer("Вы уже зарегистрированы в боте")
                    referrer_id = None
                    
            except ValueError:
                logger.warning(f"Invalid referral format for user {user_id}")
                referrer_id = None
        
        # Регистрируем/обновляем пользователя
        await db.add_user(
            user_id=user_id,
            username=message.from_user.username,
            fullname=message.from_user.full_name,
            referrer_id=referrer_id
        )
        
        if referrer_id and referrer_id != user_id:
            try:
                current_count = await db.get_invited_count(referrer_id)
                new_count = current_count + 1
                await db.update_user_invited_count(referrer_id, new_count)
                await google_api_service.update_giveaway_stats()
                
                # Отправляем уведомление рефереру
                try:
                    await bot.send_message(
                        referrer_id,
                        f"🎉 По вашей ссылке зарегистрировался новый пользователь: "
                        f"@{message.from_user.username or message.from_user.full_name}\n"
                        f"Теперь у вас {current_count + 1} приглашенных друзей!"
                    )
                except Exception as e:
                    logger.error(f"Error sending referral notification to {referrer_id}: {str(e)}")
            except Exception as e:
                logger.error(f"Error updating referral count for {referrer_id}: {str(e)}")
        
        await message.answer(
            "Добро пожаловать в бота для розыгрышей!",
            reply_markup=await kb.get_main_menu_keyboard(is_admin(message.from_user.id)))
        logger.info(f"User {user_id} started bot successfully")
    except Exception as e:
        logger.error(f"Error in start_handler: {str(e)}")
        await message.answer("Произошла ошибка при обработке запроса.")


@router.message(F.text == "Список активных розыгрышей")
async def show_active_giveaways(message: Message):
    try:
        active_giveaways = await db.get_active_giveaways()
        
        if not active_giveaways:
            await message.answer("🎉 На данный момент нет активных розыгрышей.\n"
                               "Следите за новостями, скоро будут новые!")
            return
        
        await message.answer(
            "Активные розыгрыши:",
            reply_markup=await kb.get_giveaways_list_keyboard(active_giveaways))
        logger.info(f"Active giveaways shown to user {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in show_active_giveaways: {str(e)}")
        await message.answer("Произошла ошибка при получении списка розыгрышей.")


@router.message(F.text == "Приведи друга")
async def show_referral_info(message: Message):
    try:
        user_id = message.from_user.id
        user = await db.get_user_info(user_id)
        
        if not user:
            logger.warning(f"Unregistered user {user_id} tried to access referral info")
            return await message.answer("Сначала зарегистрируйтесь с помощью /start")
        
        referrals = await db.get_user_referrals(user_id)
        invited_count = len(referrals)
        
        await message.answer(
            f"Ваша реферальная ссылка: t.me/{Config.BOT_USERNAME}?start={user_id}\n"
            f"Приглашено друзей: {invited_count}\n",
            reply_markup=await kb.get_referral_keyboard(user_id))
        logger.info(f"Referral info shown to user {user_id}")
    except Exception as e:
        logger.error(f"Error in show_referral_info for user {user_id}: {str(e)}")
        await message.answer("Произошла ошибка при получении реферальной информации.")


@router.callback_query(F.data.startswith("participate_"))
async def participate_handler(callback: CallbackQuery):
    try:
        giveaway_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id
        
        # Проверяем что пользователь зарегистрирован в боте
        user = await db.get_user_info(user_id)
        if not user:
            logger.warning(f"Unregistered user {user_id} tried to participate in giveaway {giveaway_id}")
            return await callback.answer(
                "Для участия необходимо начать диалог с ботом в личных сообщениях",
                show_alert=True
            )
        
        # Проверяем что розыгрыш еще активен
        giveaway = await db.get_giveaway_details(giveaway_id)
        if not giveaway:
            logger.warning(f"Giveaway {giveaway_id} not found or already finished")
            return await callback.answer("Этот розыгрыш уже завершен", show_alert=True)
        
        # Проверяем что дата окончания еще не наступила
        from datetime import datetime
        try:
            end_date = datetime.strptime(giveaway['announcement_date'], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            end_date = datetime.strptime(giveaway['announcement_date'], "%d.%m.%Y %H:%M")
        
        if datetime.now() > end_date:
            logger.warning(f"Giveaway {giveaway_id} already finished (date passed)")
            return await callback.answer("Этот розыгрыш уже завершен", show_alert=True)
        
        # Проверяем, что пользователь не бот
        if callback.from_user.is_bot:
            logger.warning(f"Bot {user_id} tried to participate in giveaway {giveaway_id}")
            return await callback.answer("Боты не могут участвовать в розыгрышах.")
        
        # Проверяем, не участвует ли уже пользователь
        participants = await db.get_participants(giveaway_id)
        if user_id in participants:
            logger.info(f"User {user_id} already participates in giveaway {giveaway_id}")
            return await callback.answer("Вы уже участвуете в этом розыгрыше!")
        
        await db.add_participant(giveaway_id, user_id)
        await callback.answer("Вы успешно записаны на розыгрыш!")
        logger.info(f"User {user_id} added to giveaway {giveaway_id}")
    except Exception as e:
        logger.error(f"Error in participate_handler for user {callback.from_user.id}: {str(e)}")
        await callback.answer("Произошла ошибка при записи на розыгрыш.")


@router.message(F.text == "Создать розыгрыш")
async def create_giveaway_start(message: Message, state: FSMContext):
    try:
        if not is_admin(message.from_user.id):
            logger.warning(f"Non-admin user {message.from_user.id} tried to create giveaway")
            return await message.answer("Доступ запрещен")
        
        await state.set_state(GiveawayStates.name)
        await message.answer("Введите название розыгрыша:", reply_markup= await kb.remove_keyboard())
        logger.info(f"Admin {message.from_user.id} started giveaway creation")
    except Exception as e:
        logger.error(f"Error in create_giveaway_start: {str(e)}")
        await message.answer("Произошла ошибка при создании розыгрыша")


@router.message(GiveawayStates.name)
async def set_giveaway_name(message: Message, state: FSMContext):
    try:
        await state.update_data(name=message.text)
        await state.set_state(GiveawayStates.winners_count)
        await message.answer(
            "Введите количество победителей:",
            reply_markup=await kb.remove_keyboard())
        logger.info(f"Giveaway name set: {message.text}")
    except Exception as e:
        logger.error(f"Error in set_giveaway_name: {str(e)}")
        await message.answer("Произошла ошибка при обработке названия")


@router.message(F.text == "Все розыгрыши")
async def show_all_giveaways(message: Message):
    try:
        if not is_admin(message.from_user.id):
            logger.warning(f"Non-admin user {message.from_user.id} tried to view all giveaways")
            return await message.answer("Доступ запрещен")
        
        giveaways = await db.get_all_giveaways()
        active_giveaways = []
        from datetime import datetime
        
        for giveaway in giveaways:
            try:
                try:
                    end_date = datetime.strptime(giveaway['announcement_date'], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    end_date = datetime.strptime(giveaway['announcement_date'], "%d.%m.%Y %H:%M")
                
                if datetime.now() < end_date:
                    active_giveaways.append(giveaway)
            except ValueError as e:
                logger.warning(f"Invalid date format in giveaway {giveaway.get('id')}: {giveaway.get('announcement_date')}")
                continue
        
        if not active_giveaways:
            logger.info("No active giveaways found")
            return await message.answer("Нет активных розыгрышей!")
        
        for giveaway in active_giveaways:
            try:
                display_date = datetime.strptime(giveaway['announcement_date'], "%Y-%m-%d %H:%M:%S")
                display_date = display_date.strftime("%d.%m.%Y %H:%M")
            except ValueError:
                display_date = giveaway['announcement_date']
            
            await message.answer(
                f"Розыгрыш: {giveaway['name']}\n"
                f"Победителей: {giveaway['winners_count']}\n"
                f"Дата окончания: {display_date}",
                reply_markup=await kb.get_giveaway_management_keyboard(giveaway['id']))
        logger.info(f"Active giveaways shown to admin {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in show_all_giveaways: {str(e)}")
        await message.answer("Произошла ошибка при получении списка розыгрышей")


@router.message(GiveawayStates.winners_count)
async def set_giveaway_winners_count(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Пожалуйста, введите число")
            return
        
        await state.update_data(winners_count=int(message.text))
        await state.set_state(GiveawayStates.announcement_date)
        await message.answer(
            "Введите дату и время объявления результатов (формат: ДД.ММ.ГГГГ ЧЧ:ММ):",
            reply_markup= await kb.remove_keyboard())
        logger.info(f"Giveaway winners count set: {message.text}")
    except Exception as e:
        logger.error(f"Error in set_giveaway_winners_count: {str(e)}")
        await message.answer("Произошла ошибка при обработке количества победителей")


@router.message(GiveawayStates.announcement_date)
async def set_giveaway_announcement_date(message: Message, state: FSMContext):
    try:
        from datetime import datetime
        datetime.strptime(message.text, "%d.%m.%Y %H:%M")
    except ValueError:
        logger.warning(f"Invalid date format: {message.text}")
        return await message.answer(
            "Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ",
            reply_markup=await kb.remove_keyboard())
    
    try:
        await state.update_data(announcement_date=message.text)
        await state.set_state(GiveawayStates.channel_selection)
        
        channels = await db.get_connected_channels()
        if channels:
            await message.answer(
                "Выберите каналы для розыгрыша (нажмите для выбора):",
                reply_markup=await kb.get_channels_selection_keyboard(channels))
            logger.info(f"Giveaway announcement date set: {message.text}")
        else:
            await message.answer("Нет подключенных каналов. Сначала подключите канал.")
            await state.clear()
            logger.warning("No channels available for giveaway")
    except Exception as e:
        logger.error(f"Error in set_giveaway_announcement_date: {str(e)}")
        await message.answer("Произошла ошибка при обработке даты")


@router.callback_query(F.data.startswith("toggle_channel_"), GiveawayStates.channel_selection)
async def toggle_channel_selection(callback: CallbackQuery, state: FSMContext):
    try:
        channel_id = int(callback.data.split("_")[2])
        data = await state.get_data()
        
        selected_channels = data.get("selected_channels", [])
        
        if channel_id in selected_channels:
            selected_channels.remove(channel_id)
        else:
            selected_channels.append(channel_id)
        
        await state.update_data(selected_channels=selected_channels)
        
        channels = await db.get_connected_channels()
        await callback.message.edit_reply_markup(
            reply_markup=await kb.get_channels_selection_keyboard(channels, selected_channels))
        await callback.answer()
        logger.info(f"Channel {channel_id} toggled in selection")
    except Exception as e:
        logger.error(f"Error in toggle_channel_selection: {str(e)}")
        await callback.answer("Произошла ошибка при выборе канала")


@router.callback_query(F.data == "save_channels", GiveawayStates.channel_selection)
async def save_channels_selection(callback: CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        selected_channels = data.get("selected_channels", [])
        
        if not selected_channels:
            logger.warning("No channels selected for giveaway")
            await callback.answer("Выберите хотя бы один канал!", show_alert=True)
            return
        
        await state.set_state(GiveawayStates.confirmation)
        
        # Формируем список названий каналов
        channel_names = []
        for channel_id in selected_channels:
            channel = await db.get_channel(channel_id)
            channel_names.append(channel[1] if channel else f"Канал {channel_id}")
        
        await callback.message.edit_text(
            f"Подтвердите создание розыгрыша:\n\n"
            f"Название: {data['name']}\n"
            f"Победителей: {data['winners_count']}\n"
            f"Дата окончания: {data['announcement_date']}\n"
            f"Каналы: {', '.join(channel_names)}\n\n"
            f"Продолжить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_giveaway")],
                [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_giveaway")]
            ]))
        await callback.answer()
        logger.info("Channels selection saved, confirmation requested")
    except Exception as e:
        logger.error(f"Error in save_channels_selection: {str(e)}")
        await callback.answer("Произошла ошибка при сохранении выбора каналов")


@router.callback_query(F.data == "confirm_giveaway", GiveawayStates.confirmation)
async def confirm_giveaway(callback: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        data = await state.get_data()
        selected_channels = data.get("selected_channels", [])
        
        if not selected_channels:
            logger.error("No channels selected in confirmation")
            await callback.answer("Ошибка: не выбраны каналы", show_alert=True)
            return
        
        from datetime import datetime
        announcement_date = datetime.strptime(data['announcement_date'], "%d.%m.%Y %H:%M")
        sql_date = announcement_date.strftime("%Y-%m-%d %H:%M:%S")
        
        giveaway_id = None
        for channel_id in selected_channels:
            giveaway_id = await db.create_giveaway(
                name=data['name'],
                winners_count=data['winners_count'],
                announcement_date=sql_date,
                channel_id=channel_id
            )
            
            # Добавляем задачу в планировщик
            scheduler.add_job(
                announce_giveaway_results,
                trigger=DateTrigger(announcement_date),
                args=[bot, giveaway_id],
                id=f"giveaway_{giveaway_id}"
            )
            
            # Публикуем сообщение в канале
            try:
                await bot.send_message(
                    chat_id=channel_id,
                    text=(
                        f"🎉 Новый розыгрыш!\n\n"
                        f"🏆 Название: {data['name']}\n"
                        f"👑 Количество победителей: {data['winners_count']}\n"
                        f"⏰ Дата окончания: {data['announcement_date']}\n\n"
                        f"Для участия нажмите кнопку ниже!"
                    ),
                    reply_markup=await kb.get_participate_keyboard(giveaway_id)
                )
            except Exception as e:
                logger.error(f"Error posting giveaway to channel {channel_id}: {str(e)}")
        
        await callback.message.edit_text("Розыгрыш создан!")
        await callback.message.answer(
            f"🎉 Новый розыгрыш!\n\n"
            f"🏆 Название: {data['name']}\n"
            f"👑 Количество победителей: {data['winners_count']}\n"
            f"⏰ Дата окончания: {data['announcement_date']}\n\n",
            reply_markup= await kb.get_main_menu_keyboard(is_admin(callback.from_user.id)))
        await state.clear()
        logger.info(f"Giveaway {giveaway_id} created successfully in channels {selected_channels}")
    except Exception as e:
        logger.error(f"Error in confirm_giveaway: {str(e)}")
        await callback.message.answer("Произошла ошибка при создании розыгрыша")
        await state.clear()


@router.callback_query(F.data.startswith("select_winners_"))
async def select_winners_start(callback: CallbackQuery):
    try:
        giveaway_id = int(callback.data.split("_")[2])
        
        giveaway = await db.get_giveaway_details(giveaway_id)
        if not giveaway:
            logger.warning(f"Giveaway {giveaway_id} not found")
            return await callback.answer("Этот розыгрыш уже завершен", show_alert=True)
        
        participants = await db.get_participants(giveaway_id)
        
        if not participants:
            logger.warning(f"No participants in giveaway {giveaway_id}")
            return await callback.answer("Нет участников для этого розыгрыша", show_alert=True)
        
        await callback.message.edit_text(
            f"Выберите победителей (страница 1):",
            reply_markup=await kb.get_winners_selection_keyboard(giveaway_id, participants, 0))
        await callback.answer()
        logger.info(f"Winner selection started for giveaway {giveaway_id}")
    except Exception as e:
        logger.error(f"Error in select_winners_start: {str(e)}")
        await callback.answer("Произошла ошибка при выборе победителей")


@router.callback_query(F.data.startswith("winner_"))
async def toggle_winner(callback: CallbackQuery):
    try:
        parts = callback.data.split('_')
        giveaway_id = int(parts[1])
        user_id = int(parts[2])
        page = int(parts[3])
        
        giveaway = await db.get_giveaway_details(giveaway_id)
        if not giveaway:
            logger.warning(f"Giveaway {giveaway_id} not found in toggle_winner")
            return await callback.answer("Розыгрыш не найден", show_alert=True)
        
        current_winners = json.loads(giveaway['winners_ids']) if giveaway['winners_ids'] else []
        
        if user_id in current_winners:
            current_winners.remove(user_id)
        else:
            if len(current_winners) >= giveaway['winners_count']:
                logger.info(f"Winner limit reached for giveaway {giveaway_id}")
                return await callback.answer(
                    f"Достигнут лимит в {giveaway['winners_count']} победителей", 
                    show_alert=True
                )
            current_winners.append(user_id)
        
        await db.set_winners(giveaway_id, current_winners)
        
        # Обновляем клавиатуру
        participants = await db.get_participants(giveaway_id)
        await callback.message.edit_reply_markup(
            reply_markup=await kb.get_winners_selection_keyboard(giveaway_id, participants, page))
        await callback.answer()
        logger.info(f"Winner {user_id} toggled for giveaway {giveaway_id}")
    except Exception as e:
        logger.error(f"Error in toggle_winner: {str(e)}")
        await callback.answer("Произошла ошибка при выборе победителя")


@router.callback_query(F.data.startswith("delete_giveaway_"))
async def delete_giveaway_handler(callback: CallbackQuery):
    try:
        giveaway_id = int(callback.data.split("_")[2])
        
        # Удаляем задачу из планировщика, если она есть
        try:
            scheduler.remove_job(f"giveaway_{giveaway_id}")
        except Exception as e:
            logger.warning(f"Job giveaway_{giveaway_id} not found in scheduler: {str(e)}")
        
        success = await db.delete_giveaway(giveaway_id)
        if success:
            await callback.message.answer("Розыгрыш и все связанные данные успешно удалены")
            logger.info(f"Giveaway {giveaway_id} deleted successfully")
        else:
            await callback.message.answer("Произошла ошибка при удалении розыгрыша")
            logger.error(f"Error deleting giveaway {giveaway_id}")
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in delete_giveaway_handler: {str(e)}")
        await callback.answer("Произошла ошибка при удалении розыгрыша")


@router.callback_query(F.data.startswith("copy_ref_"))
async def copy_referral_link(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split("_")[2])
        referral_link = f"t.me/{Config.BOT_USERNAME}?start={user_id}"
        await callback.answer(f"Ссылка скопирована: {referral_link}", show_alert=True)
        logger.info(f"Referral link copied for user {user_id}")
    except Exception as e:
        logger.error(f"Error in copy_referral_link: {str(e)}")
        await callback.answer("Произошла ошибка при копировании ссылки")


@router.callback_query(F.data.startswith("winners_page_"))
async def handle_winners_pagination(callback: CallbackQuery):
    try:
        _, _, giveaway_id, page = callback.data.split('_')
        giveaway_id = int(giveaway_id)
        page = int(page)
        
        participants = await db.get_participants(giveaway_id)
        await callback.message.edit_reply_markup(
            reply_markup=await kb.get_winners_selection_keyboard(giveaway_id, participants, page))
        await callback.answer()
        logger.info(f"Winners page changed to {page} for giveaway {giveaway_id}")
    except Exception as e:
        logger.error(f"Error in handle_winners_pagination: {str(e)}")
        await callback.answer("Произошла ошибка при переключении страницы")


@router.callback_query(F.data.startswith("save_winners_"))
async def save_winners_handler(callback: CallbackQuery):
    try:
        giveaway_id = int(callback.data.split("_")[2])
        giveaway = await db.get_giveaway_details(giveaway_id)
        
        if not giveaway:
            logger.warning(f"Giveaway {giveaway_id} not found in save_winners_handler")
            return await callback.answer("Розыгрыш не найден")
        
        current_winners = json.loads(giveaway['winners_ids']) if giveaway['winners_ids'] else []
        
        if not current_winners:
            logger.info(f"No winners selected for giveaway {giveaway_id}")
            return await callback.answer("Не выбрано ни одного победителя")
        
        await callback.message.answer(
            f"Сохранено {len(current_winners)} гарантированных победителя. "
            f"Остальные будут определены автоматически {giveaway['announcement_date']}.")
        await callback.answer()
        logger.info(f"Winners saved for giveaway {giveaway_id}: {current_winners}")
    except Exception as e:
        logger.error(f"Error in save_winners_handler: {str(e)}")
        await callback.answer("Произошла ошибка при сохранении победителей")


@router.message(F.text == "Подключенные каналы")
async def show_connected_channels(message: Message, state: FSMContext):
    try:
        if not is_admin(message.from_user.id):
            logger.warning(f"Non-admin user {message.from_user.id} tried to view connected channels")
            return await message.answer("Доступ запрещен")
        
        # Кнопка для добавления нового канала
        add_button = InlineKeyboardButton(
            text="➕ Добавить канал", 
            callback_data="add_channel"
        )
        
        channels = await db.get_connected_channels()
        if channels:
            channels_text = "Подключенные каналы:\n" + "\n".join(
                f"{i+1}. {channel[1]} (ID: {channel[0]})" 
                for i, channel in enumerate(channels))
            await message.answer(
                channels_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[add_button]]))
            logger.info(f"Connected channels shown to admin {message.from_user.id}")
        else:
            await message.answer(
                "Нет подключенных каналов",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[add_button]]))
            logger.info("No connected channels found")
    except Exception as e:
        logger.error(f"Error in show_connected_channels: {str(e)}")
        await message.answer("Произошла ошибка при получении списка каналов")


@router.callback_query(F.data == "add_channel")
async def start_add_channel(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.answer(
            "Отправьте мне @username канала или его ID.\n"
            "Бот должен быть администратором в этом канале!",
            reply_markup=await kb.remove_keyboard())
        await state.set_state(ChannelStates.waiting_for_channel)
        await callback.answer()
        logger.info(f"Admin {callback.from_user.id} started channel addition")
    except Exception as e:
        logger.error(f"Error in start_add_channel: {str(e)}")
        await callback.answer("Произошла ошибка при добавлении канала")


@router.message(ChannelStates.waiting_for_channel)
async def process_channel_input(message: Message, state: FSMContext, bot: Bot):
    try:
        channel_input = message.text.strip()
        
        # Пробуем получить ID канала
        if channel_input.startswith('@'):
            chat = await bot.get_chat(channel_input)
            channel_id = chat.id
            channel_title = chat.title
        else:
            channel_id = int(channel_input)
            chat = await bot.get_chat(channel_id)
            channel_title = chat.title
        
        # Проверяем права бота в канале
        try:
            chat_member = await bot.get_chat_member(channel_id, bot.id)
            if chat_member.status not in ['administrator', 'creator']:
                raise Exception("Бот не является администратором канала")
        except Exception as e:
            logger.warning(f"Bot is not admin in channel {channel_id}: {str(e)}")
            await message.answer(
                f"Ошибка: {str(e)}\n"
                "Добавьте бота как администратора в канал и попробуйте снова.")
            return
        
        # Сохраняем данные и запрашиваем подтверждение
        await state.update_data(
            channel_id=channel_id,
            channel_title=channel_title
        )
        
        confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_channel"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_channel")
            ]
        ])
        
        await message.answer(
            f"Подтвердите добавление канала:\n"
            f"Название: {channel_title}\n"
            f"ID: {channel_id}",
            reply_markup=confirm_keyboard)
        await state.set_state(ChannelStates.confirm_channel)
        logger.info(f"Channel {channel_id} ready for confirmation")
    except Exception as e:
        logger.error(f"Error in process_channel_input: {str(e)}")
        await message.answer("Проверьте правильность ввода и попробуйте снова.")


@router.callback_query(F.data == "confirm_channel", ChannelStates.confirm_channel)
async def confirm_add_channel(callback: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        data = await state.get_data()
        channel_id = data['channel_id']
        channel_title = data['channel_title']
        
        # Добавляем канал в БД
        await db.add_channel(channel_id, channel_title)
        
        # Отправляем сообщение в канал
        try:
            await bot.send_message(
                channel_id,
                f"🎉 Этот канал подключен к боту розыгрышей!\n"
                f"Теперь здесь можно проводить розыгрыши."
            )
        except Exception as e:
            logger.error(f"Error sending welcome message to channel {channel_id}: {str(e)}")

        await callback.message.answer(
            f"Канал {channel_title} успешно добавлен!",
            reply_markup=await kb.get_main_menu_keyboard(True))
        await state.clear()
        logger.info(f"Channel {channel_id} added successfully")
    except Exception as e:
        logger.error(f"Error in confirm_add_channel: {str(e)}")
        await callback.message.answer(
            f"Ошибка при добавлении канала: {str(e)}",
            reply_markup=await kb.get_main_menu_keyboard(True))
        await state.clear()
    finally:
        await callback.answer()


@router.callback_query(F.data == "cancel_channel", ChannelStates.confirm_channel)
async def cancel_add_channel(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.answer(
            "Добавление канала отменено",
            reply_markup=await kb.get_main_menu_keyboard(True))
        await state.clear()
        logger.info("Channel addition cancelled")
    except Exception as e:
        logger.error(f"Error in cancel_add_channel: {str(e)}")
    finally:
        await callback.answer()


@router.message(F.text == "Сделать рассылку")
async def start_broadcast(message: Message, state: FSMContext):
    try:
        if not is_admin(message.from_user.id):
            logger.warning(f"Non-admin user {message.from_user.id} tried to start broadcast")
            return await message.answer("Доступ запрещен")
        
        await state.set_state(BroadcastStates.waiting_for_text)
        await message.answer(
            "Введите текст для рассылки:",
            reply_markup=await kb.remove_keyboard())
        logger.info(f"Admin {message.from_user.id} started broadcast creation")
    except Exception as e:
        logger.error(f"Error in start_broadcast: {str(e)}")
        await message.answer("Произошла ошибка при создании рассылки")


@router.message(BroadcastStates.waiting_for_text)
async def process_broadcast_text(message: Message, state: FSMContext):
    try:
        await state.update_data(text=message.text)
        await state.set_state(BroadcastStates.waiting_for_photos)
        await message.answer(
            "Отправьте до 10 фото для рассылки или нажмите 'Пропустить прикрепление фото'",
            reply_markup=await kb.get_broadcast_keyboard())
        logger.info("Broadcast text received")
    except Exception as e:
        logger.error(f"Error in process_broadcast_text: {str(e)}")
        await message.answer("Произошла ошибка при обработке текста рассылки")


@router.message(BroadcastStates.waiting_for_photos, F.text == "Пропустить прикрепление фото")
async def skip_photos(message: Message, state: FSMContext):
    try:
        await state.update_data(photos=[])
        await state.set_state(BroadcastStates.confirmation)
        data = await state.get_data()
        
        await message.answer(
            f"Текст рассылки:\n\n{data['text']}\n\n"
            "Фото: не прикрепляются\n\n"
            "Подтвердите рассылку:",
            reply_markup=await kb.get_broadcast_confirmation_keyboard())
        logger.info("Photos skipped for broadcast")
    except Exception as e:
        logger.error(f"Error in skip_photos: {str(e)}")
        await message.answer("Произошла ошибка при обработке запроса")


@router.message(BroadcastStates.waiting_for_photos, F.photo)
async def process_broadcast_photos(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        photos = data.get("photos", [])
        
        if len(photos) >= 10:
            logger.warning("Maximum 10 photos reached for broadcast")
            return await message.answer("Максимум 10 фото. Нажмите 'Подтвердить рассылку'")
        
        photos.append(message.photo[-1].file_id)
        await state.update_data(photos=photos)
        await message.answer(f"Фото {len(photos)}/10 добавлено")
        logger.info(f"Photo {len(photos)} added to broadcast")
    except Exception as e:
        logger.error(f"Error in process_broadcast_photos: {str(e)}")
        await message.answer("Произошла ошибка при обработке фото")


@router.message(BroadcastStates.waiting_for_photos, F.text == "Прикрепить фото")
async def confirm_photos(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        if not data.get("photos"):
            logger.warning("No photos attached for broadcast")
            await message.answer("Вы не отправили ни одного фото!")
            return
        
        await state.set_state(BroadcastStates.confirmation)
        await message.answer(
            f"Текст рассылки:\n\n{data['text']}\n\n"
            f"Фото: {len(data['photos'])} шт.\n\n",
            reply_markup=await kb.get_broadcast_confirmation_keyboard())
        logger.info(f"Broadcast with {len(data['photos'])} photos ready for confirmation")
    except Exception as e:
        logger.error(f"Error in confirm_photos: {str(e)}")
        await message.answer("Произошла ошибка при обработке фото")


@router.message(BroadcastStates.confirmation, F.text == "Подтвердить рассылку")
async def approve_broadcast(message: Message, state: FSMContext, bot: Bot):
    try:
        data = await state.get_data()
        all_users = await db.get_all_users()
        users = [user for user in all_users if not is_admin(user['user_id'])]
        
        success = 0
        
        for user in users:
            try:
                if data.get("photos"):
                    media = [InputMediaPhoto(media=photo) for photo in data["photos"]]
                    media[0].caption = data["text"]
                    media[0].parse_mode = "HTML"
                    await bot.send_media_group(chat_id=user["user_id"], media=media)
                else:
                    await bot.send_message(
                        chat_id=user["user_id"],
                        text=data["text"],
                        parse_mode="HTML"
                    )
                success += 1
                await sleep(0.1)
            except Exception as e:
                logger.warning(f"Error sending broadcast to user {user['user_id']}: {str(e)}")
        
        await message.answer(f"Сообщения успешно отправлены {success} пользователям", 
                           reply_markup= await kb.get_main_menu_keyboard(is_admin(message.from_user.id)))
        await state.clear()
        logger.info(f"Broadcast sent to {success} users successfully")
    except Exception as e:
        logger.error(f"Error in approve_broadcast: {str(e)}")
        await message.answer("Произошла ошибка при отправке рассылки")
        await state.clear()


@router.message(F.text == "Отменить рассылку", StateFilter(BroadcastStates.waiting_for_photos, BroadcastStates.confirmation))
async def cancel_broadcast(message: Message, state: FSMContext):
    try:
        await state.clear()
        await message.answer("❌ Рассылка отменена", 
                           reply_markup=await kb.get_main_menu_keyboard(is_admin(message.from_user.id)))
        logger.info("Broadcast cancelled")
    except Exception as e:
        logger.error(f"Error in cancel_broadcast: {str(e)}")
        await message.answer("Произошла ошибка при отмене рассылки")


@router.callback_query(F.data == "check_subscriptions")
async def check_subscriptions_handler(callback: CallbackQuery, bot: Bot):
    try:
        user_id = callback.from_user.id
        
        # Пропускаем проверку для админов
        if is_admin(user_id):
            await callback.message.delete()
            await start_handler(callback.message, FSMContext(), bot)
            return
        
        unsubscribed = await check_user_subscriptions(bot, user_id)
        
        if unsubscribed:
            # Создаем новую клавиатуру
            new_keyboard = await get_subscription_check_keyboard(unsubscribed)
            
            # Проверяем, изменились ли каналы для подписки
            current_text = callback.message.text
            new_text = f"Для использования бота необходимо подписаться на следующие каналы:"
            
            if current_text != new_text:
                await callback.message.edit_text(
                    text=new_text,
                    reply_markup=new_keyboard
                )
            else:
                await callback.answer("Вы всё ещё не подписаны на все каналы!", show_alert=True)
            logger.info(f"Subscription check for user {user_id}: still not subscribed")
        else:
            await callback.message.delete()
            await start_handler(callback.message, FSMContext(), bot)
            logger.info(f"User {user_id} passed subscription check")
    except Exception as e:
        logger.error(f"Error in check_subscriptions_handler: {str(e)}")
        await callback.answer("Произошла ошибка при проверке подписки", show_alert=True)


@router.callback_query(F.data == "cancel_giveaway", GiveawayStates.confirmation)
async def cancel_giveaway_creation(callback: CallbackQuery, state: FSMContext):
    try:
        await state.clear()
        await callback.message.edit_text(
            "❌ Создание розыгрыша отменено",
            reply_markup=await kb.get_main_menu_keyboard(is_admin(callback.from_user.id)))
        logger.info("Giveaway creation cancelled")
    except Exception as e:
        logger.error(f"Error in cancel_giveaway_creation: {str(e)}")
    finally:
        await callback.answer()


@router.callback_query(F.data == "cancel_giveaway")
async def cancel_giveaway_global(callback: CallbackQuery, state: FSMContext):
    try:
        current_state = await state.get_state()
        if current_state in [
            GiveawayStates.name,
            GiveawayStates.winners_count,
            GiveawayStates.announcement_date,
            GiveawayStates.channel_selection,
            GiveawayStates.confirmation
        ]:
            await state.clear()
            await callback.message.edit_text(
                "❌ Создание розыгрыша отменено",
                reply_markup=await kb.get_main_menu_keyboard(is_admin(callback.from_user.id)))
            logger.info("Giveaway creation cancelled")
    except Exception as e:
        logger.error(f"Error in cancel_giveaway_global: {str(e)}")
    finally:
        await callback.answer()


async def check_user_subscriptions(bot: Bot, user_id: int):
    """Проверяет подписку пользователя на обязательные каналы"""
    try:
        required_channels = await google_api_service.get_subscription_channels()
        if not required_channels:
            return None
            
        unsubscribed = []
        
        for channel in required_channels:
            try:
                # Преобразуем ID канала к integer
                channel_id = int(channel['channel_id'])
                
                # Проверяем подписку пользователя
                try:
                    member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
                    if member.status in ['member', 'administrator', 'creator']:
                        continue  # Пользователь подписан
                    
                    unsubscribed.append(channel)
                
                except Exception as e:
                    if "user not found" in str(e).lower():
                        # Пользователь точно не подписан
                        unsubscribed.append(channel)
                    else:
                        logger.warning(f"Error checking user subscription for channel {channel_id}: {str(e)}")
                        unsubscribed.append(channel)
                        
            except ValueError:
                logger.warning(f"Invalid channel ID format: {channel['channel_id']}")
                continue
                
        return unsubscribed if unsubscribed else None
    except Exception as e:
        logger.error(f"Error in check_user_subscriptions: {str(e)}")
        return None


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