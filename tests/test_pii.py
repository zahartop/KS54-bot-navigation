from src.utils.pii import mask_pii


def test_mask_pii_masks_email_phone_and_fio() -> None:
    text = "Новая заявка: Иван Иванов, +79991234130, bannyhzakhar@gmail.com"
    masked = mask_pii(text)

    assert "Иван Иванов" not in masked
    assert "+79991234130" not in masked
    assert "bannyhzakhar@gmail.com" not in masked

    assert "И***** И." in masked
    assert "+7*******130" in masked
    assert "b*******@gmail.com" in masked


def test_mask_pii_keeps_text_without_pii_unchanged() -> None:
    text = "Сервис временно недоступен, повторите позже."
    assert mask_pii(text) == text


def test_mask_pii_masks_connection_string_password_in_url() -> None:
    text = (
        "ошибка подключения postgresql+asyncpg://appuser:SuperSecret@db:5432/college_db "
        "mysql://root:mysql_pass@127.0.0.1:3306/db"
    )
    masked = mask_pii(text)
    assert "SuperSecret" not in masked
    assert "mysql_pass" not in masked
    assert "appuser:***@" in masked
    assert "root:***@" in masked
    assert "postgresql+asyncpg://appuser:***@db:5432/college_db" in masked
