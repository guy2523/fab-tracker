# pkg/notion_ops.py
from __future__ import annotations

from typing import Iterable, Optional
from notion_client import Client as NotionClient
from notion.pkg.eeroq_notion import Page, Database
from notion_client.helpers import get_id


# ----------------------------------------------------------------------
# Core client helper
# ----------------------------------------------------------------------

def get_notion_client(notion_token: str) -> NotionClient:
    if not notion_token:
        raise ValueError("notion_token is required")
    return NotionClient(auth=notion_token)


# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------

def normalize_page_id(pid: str) -> str:
    """
    Accept 32-char id without dashes and convert to dashed form.
    """
    pid = (pid or "").strip()
    if not pid:
        return ""
    if len(pid) == 32 and "-" not in pid:
        return f"{pid[0:8]}-{pid[8:12]}-{pid[12:16]}-{pid[16:20]}-{pid[20:32]}"
    return pid


# ----------------------------------------------------------------------
# Archive page (with optional relation clearing)
# ----------------------------------------------------------------------

def archive_page(
    *,
    notion_token: str,
    page_id: str,
    archived: bool = True,
    clear_relations: bool = False,
) -> None:
    page_id = normalize_page_id(page_id)
    if not page_id:
        raise ValueError("page_id is required")

    client = get_notion_client(notion_token)

    # 1) Clear relations first (optional, matches your script)
    if archived and clear_relations:
        page = client.pages.retrieve(page_id=page_id)
        props = (page or {}).get("properties", {}) or {}

        rel_updates = {}
        for prop_name, prop in props.items():
            if isinstance(prop, dict) and prop.get("type") == "relation":
                rel_updates[prop_name] = {"relation": []}

        if rel_updates:
            client.pages.update(page_id=page_id, properties=rel_updates)

    # 2) Archive / unarchive
    client.pages.update(page_id=page_id, archived=bool(archived))


# ----------------------------------------------------------------------
# Create Measurement page (Bluefors / ICEOxford)
# ----------------------------------------------------------------------

def create_measure_page(
    *,
    notion_token: str,
    db_url: str,
    properties: dict,
) -> dict:
    """
    Direct replacement for notion_create_measure_page.py
    """
    if not db_url:
        raise ValueError("db_url is required")
    if not properties:
        raise ValueError("properties is required")

    _ = get_notion_client(notion_token)  # validate token

    db = Database("Measurement", url=db_url)
    page = Page()
    page.add_properties(properties)

    created = db.add_page(page)

    url = ""
    page_id = ""

    if isinstance(created, dict):
        url = created.get("url", "") or ""
        page_id = created.get("id", "") or ""
    else:
        url = getattr(created, "url", "") or getattr(page, "url", "") or ""
        page_id = getattr(created, "id", "") or getattr(page, "id", "") or ""

    return {"url": url, "page_id": page_id}


# ----------------------------------------------------------------------
# Create Fab page
# ----------------------------------------------------------------------

def create_fab_page(
    *,
    notion_token: str,
    fab_db_url: str,
    properties: dict,
) -> dict:
    if not fab_db_url:
        raise ValueError("fab_db_url is required")
    if not properties:
        raise ValueError("properties is required")

    _ = get_notion_client(notion_token)

    fab_db = Database("Fab", url=fab_db_url)
    page = Page()
    page.add_properties(properties)

    created = fab_db.add_page(page)

    url = ""
    page_id = ""

    if isinstance(created, dict):
        url = created.get("url", "") or created.get("public_url", "") or ""
        page_id = created.get("id", "") or ""
    else:
        url = getattr(created, "url", "") or getattr(page, "url", "") or ""
        page_id = getattr(created, "id", "") or getattr(page, "id", "") or ""

    return {"url": url, "page_id": page_id}


# ----------------------------------------------------------------------
# Retrieve page (used for cooldown inspection)
# ----------------------------------------------------------------------

def get_page(
    *,
    notion_token: str,
    page_id: str,
) -> dict:
    page_id = normalize_page_id(page_id)
    if not page_id:
        raise ValueError("page_id is required")

    client = get_notion_client(notion_token)
    page = client.pages.retrieve(page_id=page_id)

    props = page.get("properties") or {}
    cd = props.get("Cooldown dates") or {}
    d = (cd.get("date") or {}) if isinstance(cd, dict) else {}
    start = (d.get("start") or "").strip()

    return {
        "page_id": page.get("id", page_id),
        "url": page.get("url", ""),
        "cooldown_start_iso": start,
    }


# ----------------------------------------------------------------------
# Set relation (SAFE default, exact behavior preserved)
# ----------------------------------------------------------------------

def set_relation(
    *,
    notion_token: str,
    page_id: str,
    prop_name: str,
    related_page_ids: Optional[Iterable[str] | str],
    clear: bool = False,
) -> None:
    if not page_id:
        raise ValueError("page_id is required")
    if not prop_name:
        raise ValueError("prop_name is required")

    client = get_notion_client(notion_token)

    if clear:
        rel = []
    else:
        if related_page_ids is None:
            return
        if isinstance(related_page_ids, str):
            if not related_page_ids.strip():
                return
            rel = [{"id": related_page_ids.strip()}]
        else:
            rel = [{"id": str(x).strip()} for x in related_page_ids if str(x).strip()]
            if not rel:
                return

    client.pages.update(
        page_id=page_id,
        properties={prop_name: {"relation": rel}},
    )


# ----------------------------------------------------------------------
# Update date range (Cooldown / Warmup / Measure)
# ----------------------------------------------------------------------

def update_date_range(
    *,
    notion_token: str,
    page_id: str,
    prop_name: str,
    start_date: str,
    end_date: str | None = None,
) -> None:
    if not page_id:
        raise ValueError("page_id is required")
    if not prop_name:
        raise ValueError("prop_name is required")
    if not start_date:
        raise ValueError("start_date is required")

    client = get_notion_client(notion_token)

    date_obj = {"start": start_date}
    if end_date:
        date_obj["end"] = end_date

    client.pages.update(
        page_id=page_id,
        properties={prop_name: {"date": date_obj}},
    )


# ----------------------------------------------------------------------
# Update page properties by page_url (Fab / Measurement rename, etc.)
# ----------------------------------------------------------------------

def update_page_properties(
    *,
    notion_token: str,
    db_url: str,
    page_url: str,
    properties: dict,
) -> None:
    if not db_url:
        raise ValueError("db_url is required")
    if not page_url:
        raise ValueError("page_url is required")
    if not properties:
        raise ValueError("properties is required")

    _ = get_notion_client(notion_token)

    # Coerce "# of chips" to number (exact logic preserved)
    if "# of chips" in properties:
        try:
            properties["# of chips"] = int(float(str(properties["# of chips"]).strip()))
        except Exception:
            properties.pop("# of chips", None)

    db = Database("DB", url=db_url)
    page = Page("link", page_url)
    db.update_page_properties(page, properties)



# ----------------------------------------------------------------------
# Find page URL in database by title (Design linking)
# ----------------------------------------------------------------------

def get_page_url_by_title(
    *,
    notion_token: str,
    db_url: str,
    title: str,
) -> str:
    """
    Search a Notion database by title (contains match)
    and return the first matching page URL.
    """

    if not notion_token:
        raise ValueError("notion_token is required")
    if not db_url:
        raise ValueError("db_url is required")
    if not title:
        raise ValueError("title is required")

    client = get_notion_client(notion_token)

    db_id = get_id(db_url)

    db_info = client.databases.retrieve(db_id)
    for k, v in db_info["properties"].items():
        print(k, "->", v["type"])

    # results = client.databases.query(
    #     database_id=db_id,
    #     filter={
    #         "property": "title",
    #         "rich_text": {
    #             "contains": title,
    #         },
    #     },
    # )

    # items = results.get("results", [])
    # if not items:
    #     return ""

    # return items[0].get("url", "")