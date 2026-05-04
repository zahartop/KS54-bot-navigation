from aiogram.fsm.state import State, StatesGroup


class BroadcastForm(StatesGroup):
    composing = State()
    preview = State()
