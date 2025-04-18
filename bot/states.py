from aiogram.fsm.state import StatesGroup, State


class GiveawayStates(StatesGroup):
    name = State()
    winners_count = State()
    announcement_date = State()
    channel_selection = State()
    confirmation = State()


class ChannelStates(StatesGroup):
    waiting_for_channel = State() 
    confirm_channel = State() 


class BroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_photos = State()
    confirmation = State()