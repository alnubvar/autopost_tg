import json

from aiogram import Bot
from aiogram.types import (
    InputMediaAnimation,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    MessageEntity,
)

from keyboards.post_button import build_post_buttons_kb
from utils.logger import logger


def build_reply_markup(buttons: list[dict] | None):
    if not buttons:
        return None
    return build_post_buttons_kb(buttons)


def serialize_entities(entities: list[MessageEntity] | None) -> list[dict] | None:
    if not entities:
        return None

    serialized = []
    for entity in entities:
        if isinstance(entity, dict):
            serialized.append(entity)
        else:
            serialized.append(entity.model_dump(mode="json", exclude_none=True))
    return serialized


def deserialize_entities(entities: list[dict] | None) -> list[MessageEntity] | None:
    if not entities:
        return None

    deserialized = []
    for entity in entities:
        if isinstance(entity, MessageEntity):
            deserialized.append(entity)
        else:
            deserialized.append(MessageEntity(**entity))
    return deserialized


def normalize_text_payload(raw_content: str) -> dict:
    try:
        payload = json.loads(raw_content)
    except Exception:
        return {"text": raw_content, "entities": None}

    if isinstance(payload, dict) and "text" in payload:
        return {"text": payload.get("text") or "", "entities": payload.get("entities")}

    return {"text": raw_content, "entities": None}


def normalize_media_payload(raw_content: str) -> dict:
    payload = json.loads(raw_content)
    payload.setdefault("caption", None)
    payload.setdefault("caption_entities", None)
    return payload


def build_text_storage_payload(text: str | None, entities: list[MessageEntity] | None = None) -> str:
    return json.dumps(
        {
            "text": text or "",
            "entities": serialize_entities(entities),
        },
        ensure_ascii=False,
    )


def build_media_storage_payload(
    file_id: str,
    caption: str | None = None,
    caption_entities: list[MessageEntity] | None = None,
) -> str:
    return json.dumps(
        {
            "file_id": file_id,
            "caption": caption,
            "caption_entities": serialize_entities(caption_entities),
        },
        ensure_ascii=False,
    )


def _build_media_group(raw_content: str) -> tuple[list, str | None]:
    album = json.loads(raw_content)
    items = album.get("items", [])
    caption = album.get("caption")
    caption_entities = deserialize_entities(album.get("caption_entities"))
    media = []

    for idx, item in enumerate(items[:10]):
        current_caption = caption if idx == 0 else None
        current_entities = caption_entities if idx == 0 else None
        item_type = item["type"]
        file_id = item["file_id"]

        if item_type == "photo":
            media.append(
                InputMediaPhoto(
                    media=file_id,
                    caption=current_caption,
                    caption_entities=current_entities,
                    parse_mode=None if current_entities else None,
                )
            )
        elif item_type == "video":
            media.append(
                InputMediaVideo(
                    media=file_id,
                    caption=current_caption,
                    caption_entities=current_entities,
                    parse_mode=None if current_entities else None,
                )
            )
        elif item_type == "document":
            media.append(
                InputMediaDocument(
                    media=file_id,
                    caption=current_caption,
                    caption_entities=current_entities,
                    parse_mode=None if current_entities else None,
                )
            )
        elif item_type == "animation":
            media.append(
                InputMediaAnimation(
                    media=file_id,
                    caption=current_caption,
                    caption_entities=current_entities,
                    parse_mode=None if current_entities else None,
                )
            )

    return media, caption


async def send_post_content(
    bot: Bot,
    chat_id: int | str,
    content_type: str,
    raw_content: str,
    buttons: list[dict] | None = None,
    preview_mode: bool = False,
):
    reply_markup = build_reply_markup(buttons)

    if content_type == "text":
        payload = normalize_text_payload(raw_content)
        entities = deserialize_entities(payload.get("entities"))
        await bot.send_message(
            chat_id,
            payload["text"],
            entities=entities,
            parse_mode=None if entities else None,
            reply_markup=reply_markup,
        )
        return

    if content_type == "media_group":
        media, _caption = _build_media_group(raw_content)
        if not media:
            raise ValueError("Empty media_group payload")

        await bot.send_media_group(chat_id, media)

        if reply_markup:
            text = "Кнопки этого поста:" if preview_mode else "Ссылки к посту:"
            await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return

    payload = normalize_media_payload(raw_content)
    file_id = payload["file_id"]
    caption = payload.get("caption")
    caption_entities = deserialize_entities(payload.get("caption_entities"))

    if content_type == "photo":
        await bot.send_photo(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=None if caption_entities else None,
            reply_markup=reply_markup,
        )
    elif content_type == "video":
        await bot.send_video(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=None if caption_entities else None,
            reply_markup=reply_markup,
        )
    elif content_type == "document":
        await bot.send_document(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=None if caption_entities else None,
            reply_markup=reply_markup,
        )
    elif content_type == "voice":
        await bot.send_voice(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=None if caption_entities else None,
            reply_markup=reply_markup,
        )
    elif content_type == "audio":
        await bot.send_audio(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=None if caption_entities else None,
            reply_markup=reply_markup,
        )
    elif content_type == "animation":
        await bot.send_animation(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=None if caption_entities else None,
            reply_markup=reply_markup,
        )
    elif content_type == "video_note":
        await bot.send_video_note(chat_id, file_id)
    else:
        raise ValueError(f"Unsupported content type: {content_type}")


async def publish_to_targets(
    bot: Bot,
    chat_ids: list[str],
    content_type: str,
    raw_content: str,
    buttons: list[dict] | None = None,
) -> dict:
    delivered = 0
    failed: list[dict] = []

    for chat_id in chat_ids:
        try:
            await send_post_content(
                bot=bot,
                chat_id=chat_id,
                content_type=content_type,
                raw_content=raw_content,
                buttons=buttons,
            )
            delivered += 1
        except Exception as exc:
            failed.append({"chat_id": chat_id, "error": str(exc)})
            logger.exception("Failed to publish post to chat %s", chat_id)

    return {"delivered": delivered, "failed": failed}
