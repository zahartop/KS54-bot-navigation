from aiogram.filters.callback_data import CallbackData


class EducationLevelCallback(CallbackData, prefix="edu_level"):
    grade: str


class EducationFormCallback(CallbackData, prefix="edu_form"):
    grade: str
    form: str
