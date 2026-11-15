import pytest
from helpers import card, count, get_board, new_card, post_image, upload

from app import db

OLD = "2000-01-01T00:00:00.000Z"
BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


def test_upload_then_read_back_the_same_bytes(me):
    image = upload(me, BYTES, "image/png", "shot.png")
    assert image["file"] == "shot.png" and image["src"] == f"/api/images/{image['id']}"
    response = me.get(image["src"])
    assert response.status_code == 200
    assert response.content == BYTES
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"].startswith("private")


@pytest.mark.parametrize("mime", ["image/jpeg", "image/png", "image/webp"])
def test_the_three_image_types_are_accepted(me, mime):
    image = upload(me, b"abc", mime)
    assert me.get(image["src"]).headers["content-type"] == mime


@pytest.mark.parametrize(
    ("content", "mime"),
    [
        (b"GIF89a", "image/gif"),
        (b"<svg/>", "image/svg+xml"),
        (b"<script>alert(1)</script>", "text/html"),
        (b"plain bytes", "application/octet-stream"),
        (b"", "image/png"),  # an empty file
    ],
)
def test_bad_uploads_are_rejected(me, conn, content, mime):
    assert post_image(me, content, mime, "x.png").status_code == 422
    assert count(conn, "images", "file_name = 'x.png'") == 0


def test_a_json_body_is_not_an_image(me):
    assert me.post("/api/images?fileName=x.png", json={"dataUrl": "data:image/png;base64,AAAA"}).status_code == 422


def test_the_size_limit_is_2_mb(me, conn):
    just_fits = b"0" * (2 * 1024 * 1024)
    assert post_image(me, just_fits, file_name="ok.png").status_code == 201
    too_big = post_image(me, just_fits + b"0", file_name="big.png")
    assert too_big.status_code == 413
    assert count(conn, "images", "file_name = 'big.png'") == 0


def test_a_missing_file_name_is_rejected(me):
    assert post_image(me, file_name="").status_code == 422
    assert me.post("/api/images", content=b"abc", headers={"Content-Type": "image/png"}).status_code == 422


def test_a_non_ascii_file_name_survives(me):
    image = upload(me, file_name="عکس نمونه.png")
    assert image["file"] == "عکس نمونه.png"


def test_a_message_shows_its_image_with_a_link(me):
    image = upload(me, BYTES)
    sent = me.post("/api/spaces/general/messages", json={"text": "look", "imageId": image["id"]}).json()
    assert sent["image"] == {"file": "shot.png", "src": image["src"]}
    assert get_board(me)["messages"]["general"][-1]["image"]["src"] == image["src"]
    only_image = me.post("/api/spaces/general/messages", json={"imageId": upload(me)["id"]}).json()
    assert "text" not in only_image


def test_sample_placeholders_show_a_name_but_have_no_bytes(me, conn):
    placeholder = conn.execute("SELECT id FROM images WHERE data IS NULL LIMIT 1").fetchone()[0]
    assert me.get(f"/api/images/{placeholder}").status_code == 404
    shown = [m["image"] for m in get_board(me)["messages"]["general"] if "image" in m]
    assert shown == [{"file": "empty-states-moodboard.png"}]


def test_an_image_can_be_attached_once_and_only_by_its_uploader(me, other):
    image = upload(me)
    assert other.post("/api/spaces/general/messages", json={"imageId": image["id"]}).status_code == 422  # not theirs
    assert me.post("/api/spaces/general/messages", json={"imageId": image["id"]}).status_code == 201
    assert me.post("/api/spaces/general/messages", json={"imageId": image["id"]}).status_code == 422  # used
    assert me.post("/api/spaces/general/messages", json={"imageId": "nope"}).status_code == 422


def test_a_failed_send_leaves_no_message_behind(me, conn):
    before = count(conn, "messages")
    assert me.post("/api/spaces/general/messages", json={"text": "with a bad image", "imageId": "nope"}).status_code == 422
    assert count(conn, "messages") == before


def test_only_members_of_the_board_can_read_an_image(me, other):
    image = upload(me)
    assert other.get(image["src"]).status_code == 404
    assert me.get(image["src"]).status_code == 200
    assert me.get("/api/images/does-not-exist").status_code == 404


# ---- no orphaned images ----------------------------------------------------------------------------


def stored(conn, image_id):
    return count(conn, "images", "id = ?", (image_id,)) == 1


def test_deleting_a_message_deletes_its_image(me, conn):
    image = upload(me)
    message = me.post("/api/spaces/general/messages", json={"imageId": image["id"]}).json()
    assert stored(conn, image["id"])
    conn.execute("DELETE FROM messages WHERE id = ?", (int(message["id"]),))  # the app never does this; the database rule still holds
    assert not stored(conn, image["id"])


def test_purging_a_card_deletes_the_images_in_its_room_and_its_announcement_messages(me, conn):
    made = me.post("/api/spaces/general/tasks", json={"text": "With pictures"}).json()["card"]
    in_room = [upload(me, bytes([i]) * 10)["id"] for i in range(3)]
    for image_id in in_room:
        me.post(f"/api/spaces/{made['id']}/messages", json={"text": "pic", "imageId": image_id})
    in_general = upload(me)["id"]
    me.post("/api/spaces/general/messages", json={"imageId": in_general})
    sample_images = count(conn, "images", "data IS NULL")
    total = count(conn, "images")

    me.delete(f"/api/cards/{made['id']}")
    assert all(stored(conn, i) for i in in_room)  # still there: Undo can bring the card back
    me.post(f"/api/cards/{made['id']}/restore")
    me.delete(f"/api/cards/{made['id']}")
    conn.execute("UPDATE cards SET deleted_at = ? WHERE id = ?", (OLD, made["id"]))
    db.purge(conn)

    assert not any(stored(conn, i) for i in in_room)  # none left behind
    assert stored(conn, in_general)  # images elsewhere are untouched
    assert count(conn, "images", "data IS NULL") == sample_images
    assert count(conn, "images") == total - 3
    assert count(conn, "images", "message_id IS NOT NULL AND message_id NOT IN (SELECT id FROM messages)") == 0


def test_purging_a_sample_card_removes_its_placeholder_image(me, conn):
    task_room = card(get_board(me), "Task chat room")["id"]  # its room has a sample image message
    placeholders = count(conn, "images", "data IS NULL")
    me.delete(f"/api/cards/{task_room}")
    conn.execute("UPDATE cards SET deleted_at = ? WHERE id = ?", (OLD, task_room))
    db.purge(conn)
    assert count(conn, "images", "data IS NULL") == placeholders - 1


def test_an_upload_that_never_gets_a_message_is_purged_after_24_hours(me, conn):
    forgotten, fresh = upload(me)["id"], upload(me)["id"]
    conn.execute("UPDATE images SET created_at = ? WHERE id = ?", (OLD, forgotten))
    victim = new_card(me, "Delete me")["id"]
    me.delete(f"/api/cards/{victim}")  # every delete purges
    assert not stored(conn, forgotten)
    assert stored(conn, fresh)  # a recent upload may still get its message


def test_no_orphans_remain_after_everything_is_removed(me, conn):
    for i in range(3):
        me.post("/api/spaces/general/messages", json={"imageId": upload(me, bytes([i]) * 8)["id"]})
    conn.execute("DELETE FROM cards")  # every room, message and image under them goes too
    conn.execute("DELETE FROM messages WHERE space_id IN (SELECT id FROM spaces WHERE kind = 'general')")
    assert count(conn, "images") == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
