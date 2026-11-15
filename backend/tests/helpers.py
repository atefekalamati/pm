import base64


def name(text):
    """English of a sample text, or the text itself."""
    return text["en"] if isinstance(text, dict) else text


def get_board(client):
    response = client.get("/api/board")
    assert response.status_code == 200, response.text
    return response.json()


def card(board, title):
    return next(c for c in board["cards"].values() if name(c["title"]) == title)


def column(board, slug):
    return next(c for c in board["columns"] if c["id"] == slug)


def order(board, slug):
    """Card titles of a column, top to bottom."""
    return [name(board["cards"][i]["title"]) for i in column(board, slug)["cardIds"]]


def member(board, username_name):
    return next(m["id"] for m in board["members"].values() if name(m["name"]).startswith(username_name))


def new_card(client, title="New card", column="todo", **extra):
    response = client.post("/api/cards", json={"columnId": column, "title": title, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def events(board, space):
    return [m for m in board["messages"].get(space, []) if m["type"] == "event"]


def data_url(content=b"\x89PNG-fake-bytes", mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(content).decode()


def upload(client, content=b"\x89PNG-fake-bytes", mime="image/png", file_name="shot.png"):
    response = client.post("/api/images", json={"fileName": file_name, "dataUrl": data_url(content, mime)})
    assert response.status_code == 201, response.text
    return response.json()


def positions(conn, slug):
    """(title, position) of the live cards of a column, in order."""
    return [
        (r["title"], r["position"])
        for r in conn.execute(
            "SELECT c.title, c.position FROM cards c JOIN columns col ON col.id = c.column_id"
            " WHERE col.slug = ? AND c.deleted_at IS NULL ORDER BY c.position, c.seq",
            (slug,),
        )
    ]


def count(conn, table, where="1 = 1", args=()):
    return conn.execute(f"SELECT count(*) FROM {table} WHERE {where}", args).fetchone()[0]
