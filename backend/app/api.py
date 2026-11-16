import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from app import ai, assistant, board, images
from app.auth import current_user
from app.db import get_db, tx

router = APIRouter(prefix="/api")

Priority = Literal["low", "medium", "high"]
Title = Annotated[str, Field(min_length=1, max_length=500)]


class Ctx:
    """The signed-in user, their board and a database connection, for one request."""

    def __init__(self, conn: sqlite3.Connection, user: sqlite3.Row, board_id: str):
        self.conn, self.user, self.board_id = conn, user, board_id

    @property
    def user_id(self) -> str:
        return self.user["id"]


def ctx(user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> Ctx:
    board_id = board.board_id_of(conn, user["id"])
    if board_id is None:
        raise HTTPException(status_code=409, detail="This user has no board yet")
    return Ctx(conn, user, board_id)


def _not_blank(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("The title cannot be empty")
    return value.strip() if value else value


# ---- request bodies --------------------------------------------------------------------------------


class _WithTitle(BaseModel):
    @field_validator("title", check_fields=False)
    @classmethod
    def _title_not_blank(cls, value):
        return _not_blank(value)


class NewCard(_WithTitle):
    id: str | None = None  # the client may pick the id (a UUID), so the screen needs no id swap
    columnId: str
    title: Title
    details: str = Field(default="", max_length=20000)
    priority: Priority = "medium"
    dueDate: str | None = None
    labelIds: list[str] = []
    memberIds: list[str] = []


class CardChanges(_WithTitle):
    """Only the fields that are sent change. dueDate: null clears the date."""

    title: Title = None
    details: Annotated[str, Field(max_length=20000)] = None
    priority: Priority = None
    dueDate: str | None = None
    labelIds: list[str] = None
    memberIds: list[str] = None
    progress: Annotated[int, Field(ge=0, le=100)] = None


class MoveCard(BaseModel):
    columnId: str
    index: int = Field(ge=0)


class Assignee(BaseModel):
    userId: str


class ColumnChanges(BaseModel):
    name: Annotated[str, Field(max_length=100)] | None = None  # null or empty = the translated default name
    wipLimit: Annotated[int, Field(ge=1)] | None = None  # null = no limit
    collapsed: bool = None


class NewMessage(BaseModel):
    text: str | None = Field(default=None, max_length=5000)
    imageId: str | None = None


class NewTask(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=500)]
    cardId: str | None = None  # the client may pick the new card's id (a UUID), like for POST /cards


class AiQuestion(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=4000)]


class SettingsChanges(BaseModel):
    language: Literal["en", "fa"] = None
    density: Literal["comfortable", "compact"] = None


# ---- board -----------------------------------------------------------------------------------------


@router.get("/board")
def get_board(c: Ctx = Depends(ctx)):
    return board.load_board(c.conn, c.board_id, c.user_id)


@router.get("/settings")
def get_settings(c: Ctx = Depends(ctx)):
    return {"language": c.user["language"], "density": c.user["density"]}


@router.patch("/settings")
def patch_settings(changes: SettingsChanges, c: Ctx = Depends(ctx)):
    values = changes.model_dump(exclude_unset=True)
    if None in values.values():
        raise HTTPException(status_code=422, detail="Settings cannot be null")
    with tx(c.conn):
        for field, value in values.items():
            c.conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, c.user_id))  # field names are from the model
    row = c.conn.execute("SELECT language, density FROM users WHERE id = ?", (c.user_id,)).fetchone()
    return {"language": row["language"], "density": row["density"]}


@router.patch("/columns/{column_id}")
def patch_column(column_id: str, changes: ColumnChanges, c: Ctx = Depends(ctx)):
    values = changes.model_dump(exclude_unset=True)
    if "collapsed" in values and values["collapsed"] is None:
        raise HTTPException(status_code=422, detail="collapsed cannot be null")
    return {"columns": board.update_column(c.conn, c.board_id, column_id, values)}


# ---- cards -----------------------------------------------------------------------------------------


@router.post("/cards", status_code=201)
def create_card(card: NewCard, c: Ctx = Depends(ctx)):
    data = card.model_dump(exclude={"id", "columnId"})
    return board.create_card(c.conn, c.board_id, card.columnId, data, card.id)


@router.patch("/cards/{card_id}")
def patch_card(card_id: str, changes: CardChanges, c: Ctx = Depends(ctx)):
    values = changes.model_dump(exclude_unset=True)
    if any(v is None for k, v in values.items() if k != "dueDate"):
        raise HTTPException(status_code=422, detail="Only dueDate can be null")
    return board.update_card(c.conn, c.board_id, card_id, values)


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: str, c: Ctx = Depends(ctx)):
    board.delete_card(c.conn, c.board_id, card_id)


@router.post("/cards/{card_id}/restore")
def restore_card(card_id: str, c: Ctx = Depends(ctx)):
    return board.restore_card(c.conn, c.board_id, card_id)


@router.post("/cards/{card_id}/move")
def move_card(card_id: str, move: MoveCard, c: Ctx = Depends(ctx)):
    return {"columns": board.move_card(c.conn, c.board_id, c.user_id, card_id, move.columnId, move.index)}


@router.post("/cards/{card_id}/members", status_code=201)
def add_member(card_id: str, assignee: Assignee, c: Ctx = Depends(ctx)):
    return board.add_member(c.conn, c.board_id, c.user_id, card_id, assignee.userId)


@router.delete("/cards/{card_id}/members/{user_id}")
def remove_member(card_id: str, user_id: str, c: Ctx = Depends(ctx)):
    return board.remove_member(c.conn, c.board_id, c.user_id, card_id, user_id)


@router.post("/cards/{card_id}/post-progress", status_code=204)
def post_progress(card_id: str, c: Ctx = Depends(ctx)):
    board.post_progress(c.conn, c.board_id, c.user_id, card_id)


# ---- conversations ---------------------------------------------------------------------------------


@router.post("/spaces/{space_id}/messages", status_code=201)
def send_message(space_id: str, message: NewMessage, c: Ctx = Depends(ctx)):
    return board.send_message(c.conn, c.board_id, c.user_id, space_id, message.text, message.imageId)


@router.post("/spaces/{space_id}/tasks", status_code=201)
def create_task(space_id: str, task: NewTask, c: Ctx = Depends(ctx)):
    return board.create_task_from_message(c.conn, c.board_id, c.user_id, space_id, task.text.strip(), task.cardId)


@router.post("/spaces/{space_id}/read", status_code=204)
def mark_read(space_id: str, c: Ctx = Depends(ctx)):
    board.mark_read(c.conn, c.board_id, c.user_id, space_id)


# ---- AI --------------------------------------------------------------------------------------------


@router.get("/ai/status")
def ai_status(_user: sqlite3.Row = Depends(current_user)):
    """Whether an API key is set. The assistant panel (Part 10) shows "AI is not configured" when it is not."""
    return {"configured": ai.is_configured()}


@router.post("/ai/test")
def ai_test(_user: sqlite3.Row = Depends(current_user)):
    """Asks the model what 2+2 is: proves the key, the address and the model name work. Nothing else is touched."""
    question = "What is 2+2? Answer with just the number."
    try:
        answer = ai.complete([{"role": "user", "content": question}])
    except ai.AiNotConfigured:
        raise HTTPException(status_code=503, detail="AI is not configured") from None
    except ai.AiUnavailable as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    return {"question": question, "answer": answer.strip(), "model": ai.model()}


@router.post("/ai/chat")
def ai_chat(question: AiQuestion, c: Ctx = Depends(ctx)):
    """Ask the assistant. It answers in the language of the question and may change the board; every change it
    makes is applied together or not at all. `applied` lists the changes and `board` is the updated board. When the
    model's answer is unusable nothing changes and `reply` is a plain message (with `problem` saying why).
    Failures of the service are 502/503 with a detail in both languages: {"en": ..., "fa": ...}."""
    text = question.message.strip()
    if not text:
        raise HTTPException(status_code=422, detail="The message is empty")
    try:
        return assistant.chat(c.conn, c.board_id, c.user_id, text)
    except ai.AiNotConfigured:
        raise HTTPException(status_code=503, detail=assistant.NOT_CONFIGURED) from None
    except ai.AiUnavailable as error:
        raise HTTPException(status_code=503 if error.status in ai.RETRY_STATUSES else 502, detail=assistant.unavailable_message(error)) from None


@router.get("/ai/history")
def ai_history(c: Ctx = Depends(ctx)):
    """The last messages of the conversation with the assistant (the ones the model is sent), oldest first."""
    return assistant.history(c.conn, c.board_id, c.user_id)


# ---- images ----------------------------------------------------------------------------------------


@router.post(
    "/images",
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "The image file itself (JPEG, PNG or WebP, at most 2 MB), with its type as Content-Type.",
            "content": {t: {"schema": {"type": "string", "format": "binary"}} for t in images.IMAGE_TYPES},
        }
    },
)
async def upload_image(request: Request, fileName: str = Query(min_length=1, max_length=255), c: Ctx = Depends(ctx)):
    """Uploads an image as a file. Send the message afterwards with the returned id as `imageId`."""
    data = await request.body()
    mime_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    return await run_in_threadpool(images.store_image, c.conn, c.board_id, c.user_id, fileName, mime_type, data)


@router.get("/images/{image_id}")
def get_image(image_id: str, c: Ctx = Depends(ctx)):
    data, mime = images.read_image(c.conn, c.user_id, image_id)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})
