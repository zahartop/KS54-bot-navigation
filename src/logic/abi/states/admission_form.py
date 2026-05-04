from aiogram.fsm.state import State, StatesGroup


class ConsentState(StatesGroup):
    """Состояние ожидания согласия на обработку ПДн (ФЗ-152)."""

    waiting = State()


class AdmissionForm(StatesGroup):
    """Состояния анкеты поступающего."""

    fio = State()
    phone = State()
    email = State()


class SpecialtyRequestForm(StatesGroup):
    """Состояния анкеты для подбора специальности."""

    fio = State()
    phone = State()
    email = State()
    confirm = State()


class TestState(StatesGroup):
    """Состояния теста на подбор специализации."""

    q1 = State()
    q2 = State()
    q3 = State()
    q4 = State()
    q5 = State()
    show_result = State()
