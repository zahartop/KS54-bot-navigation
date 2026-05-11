from aiogram.fsm.state import State, StatesGroup


class ConsentState(StatesGroup):
    """Состояние ожидания согласия на обработку ПДн (ФЗ-152)."""

    waiting = State()


class AdmissionForm(StatesGroup):
    """Состояния анкеты поступающего."""

    saved_profile_choice = State()
    fio = State()
    phone = State()
    email = State()
    role = State()


class SurveyState(StatesGroup):
    """Дерево опроса перед анкетой: регион → класс → специальность."""

    region = State()
    grade = State()
    specialty = State()


class SpecialtyRequestForm(StatesGroup):
    """Состояния анкеты для подбора специальности."""

    saved_profile_choice = State()
    fio = State()
    phone = State()
    email = State()
    confirm = State()


class AppealForm(StatesGroup):
    """Состояние формы обращения в приёмную комиссию."""

    waiting_text = State()


class TestState(StatesGroup):
    """Состояния теста на подбор специализации."""

    q1 = State()
    q2 = State()
    q3 = State()
    q4 = State()
    q5 = State()
    show_result = State()
