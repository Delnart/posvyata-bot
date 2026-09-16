from sqlalchemy import select, insert, update
from app.db.db_setup import engine, admin_list, user_list


async def add_user(tg_id: int, username: str, name: str,
                   university: str = None, faculty: str = None,
                   group_name: str = None) -> None:
    """
    Inserts a new user record into the user_list database table.

    Parameters:
    tg_id (int): The unique Telegram identifier of the user.
    username (str): The Telegram username of the user.
    name (str): The full real name of the user (ПІБ).
    university (str, optional): The user's university.
    faculty (str, optional): The specific faculty or department.
    group_name (str, optional): The academic group of the user.

    Returns:
    None
    """
    async with engine.begin() as conn:
        insert_statement = insert(user_list).values(
            telegram_id=tg_id,
            username=username,
            name=name,
            university=university,
            faculty=faculty,
            group_name=group_name,
        )
        await conn.execute(insert_statement)


async def get_user(tg_id: int):
    """
    Retrieves a complete user record from the database using their Telegram ID.

    Parameters:
    tg_id (int): The unique Telegram identifier of the user to search for.

    Returns:
    sqlalchemy.engine.row.Row: A row object containing all user data if found.
    None: If no user with the specified tg_id exists in the database.
    """
    async with engine.begin() as conn:
        select_statement = select(user_list).where(user_list.c.telegram_id == tg_id)
        result = await conn.execute(select_statement)
        return result.fetchone()


async def get_all_users():
    """
    Fetches all registered users from the user_list database table.

    Returns:
    list: A list of sqlalchemy.engine.row.Row objects representing all users.
    """
    async with engine.begin() as conn:
        select_statement = select(user_list)
        result = await conn.execute(select_statement)
        return result.fetchall()


async def update_user_field(tg_id: int, field_name: str, new_value) -> None:
    """
    Updates a specific field in the user's database record.

    Parameters:
    tg_id (int): The unique Telegram identifier of the user.
    field_name (str): The exact name of the database column to change.
    new_value: The new value to insert into the specified column.

    Returns: None
    """
    allowed_fields = ["username", "name", "university", "faculty", "group_name"]

    if field_name not in allowed_fields:
        raise ValueError(f"Field '{field_name}' is not allowed to be updated.")

    async with engine.begin() as conn:
        update_data = {field_name: new_value}
        update_statement = (
            update(user_list)
            .where(user_list.c.telegram_id == tg_id)
            .values(**update_data)
        )
        await conn.execute(update_statement)


async def is_admin(user_id: int) -> bool:
    """
    Checks whether a specific user holds an active administrative role.

    Parameters:
    user_id (int): The unique Telegram identifier of the user to verify.

    Returns:
    bool: True if the user is an active administrator, False otherwise.
    """
    async with engine.begin() as conn:
        select_statement = select(admin_list).where(
            (admin_list.c.telegram_id == user_id) & (admin_list.c.is_active == True)
        )

        result = await conn.execute(select_statement)
        return result.fetchone() is not None
