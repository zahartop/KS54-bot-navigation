import pytest
from src.logic.abi.handlers.shared import (
    is_valid_email as _is_valid_email,
)
from src.logic.abi.handlers.shared import (
    is_valid_fio as _is_valid_fio,
)
from src.logic.abi.handlers.shared import (
    is_valid_phone as _is_valid_phone,
)
from src.logic.abi.handlers.shared import (
    normalize_phone as _normalize_phone,
)


@pytest.mark.parametrize(
    "fio",
    [
        "Иван Иванов",
        "Мамин-Сибиряк Иван",
        "Анна-Мария Петрова",
        "John Doe",
    ],
)
def test_fio_validation_accepts_full_name_with_hyphens(fio: str) -> None:
    assert _is_valid_fio(fio) is True


@pytest.mark.parametrize(
    "fio",
    [
        "Иван",
        "Иван123 Иванов",
        "Иван_Иванов",
        "",
        " ",
    ],
)
def test_fio_validation_rejects_invalid_values(fio: str) -> None:
    assert _is_valid_fio(fio) is False


@pytest.mark.parametrize(
    "phone",
    [
        "+79991234567",
        "+7 9991234567",
        "79991234567",
        "89991234567",
    ],
)
def test_phone_validation_accepts_required_formats(phone: str) -> None:
    assert _is_valid_phone(phone) is True


@pytest.mark.parametrize(
    "phone",
    [
        "8999123456",
        "899912345678",
        "abc",
        "",
    ],
)
def test_phone_validation_rejects_invalid_formats(phone: str) -> None:
    assert _is_valid_phone(phone) is False


@pytest.mark.parametrize(
    "email",
    [
        "bannyhzakhar@gmail.com",
        "student.name+tag@college-54.ru",
        "a@b.co",
    ],
)
def test_email_validation_accepts_standard_addresses(email: str) -> None:
    assert _is_valid_email(email) is True


@pytest.mark.parametrize(
    "email",
    [
        "bannyhzakhar@gmail",
        "bannyhzakhar@",
        "@gmail.com",
        "plainaddress",
        "a b@gmail.com",
        "",
        "bannyhzakhar@gmail.con",  # .com → .con
        "student@yandex.cmo",  # .com → .cmo
        "user@mail.nt",  # .net → .nt
    ],
)
def test_email_validation_rejects_invalid_addresses(email: str) -> None:
    assert _is_valid_email(email) is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+79991234567", "+79991234567"),
        ("89991234567", "+79991234567"),
        ("79991234567", "+79991234567"),
        ("9991234567", "+79991234567"),
        ("+7 (999) 123-45-67", "+79991234567"),
        ("8 (999) 123-45-67", "+79991234567"),
    ],
)
def test_normalize_phone_converts_to_plus7_format(raw: str, expected: str) -> None:
    assert _normalize_phone(raw) == expected


def test_normalize_phone_returns_raw_for_unrecognized_format() -> None:
    assert _normalize_phone("abc") == "abc"
    assert _normalize_phone("123") == "123"
