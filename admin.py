import os, sys
import pytz
import streamlit as st
from firebase_client import firebase_sign_in_with_google, firestore_set, firestore_get, firestore_delete, firestore_list, firestore_update_field, firestore_to_python, firebase_refresh_id_token
from datetime import datetime
from services.flow_builder import firestore_fields_to_layers, build_default_flow
from services.flow_builder import ensure_flow_ids
from services.presets import load_layer_presets_once
from services.status_editor import handle_chip_status_change
from services.flow_defaults import DEFAULT_FLOW
from core.metadata import normalize_meta, ensure_kv_rows, build_package_chip_meta, get_package_chips, get_measure_fridges, build_measure_fridge_meta
from ui.flow_editor import flow_editor, update_flow_editor
from ui.metadata_ui import render_metadata_ui, save_package_info_core, save_measure_info_core
from services.drive import upload_file_via_cleanroom_api, delete_file_via_cleanroom_api
import requests, time, json
from zoneinfo import ZoneInfo
from notion_client.helpers import get_id
from notion.notion_ops import update_page_properties, create_measure_page, set_relation, update_date_range, archive_page, get_page, create_fab_page, get_page_url_by_title
from notion.notion_add_fab_content import add_fab_content
import urllib.parse
import notion_client
import inspect

# optional card CSS (unused directly but kept for consistency)
st.markdown(
    """
<style>
.card {
    border: 1.5px solid #c8c8c8;
    border-radius: 12px;
    padding: 28px;
    background: #f6f6f6;
    margin-top: 40px;
    margin-bottom: 40px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown("""
<style>

    /* Shrink the outer container of each text_input */
    .flow-editor .stTextInput > div {
        max-width: 300px !important;
    }

    /* Shrink the inner input area */
    .flow-editor .stTextInput input {
        max-width: 300px !important;
    }

    /* Indent for chip rows */
    .flow-editor .chip-indent {
        margin-left: 60px !important;
    }

    /* ---- REAL spacing fix ---- */

    /* Remove Streamlit vertical spacing */
    div.flow-editor [data-testid="stVerticalBlock"] {
        gap: 0px !important;
    }

    /* Remove Streamlit bottom margin on each widget */
    div.flow-editor .element-container {
        margin-bottom: 0px !important;
        padding-bottom: 0px !important;
    }

    /* Tighten spacing inside columns */
    div.flow-editor [data-testid="column"] > div {
        margin-bottom: 0px !important;
        padding-bottom: 0px !important;
    }

    /* Reduce spacing around HR lines */
    div.flow-editor hr {
        margin: 4px 0 !important;
        padding: 0 !important;
    }

</style>
""", unsafe_allow_html=True)


CHI = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")


def fb_local_str_to_notion_utc_iso(fb_str: str) -> str:
    """
    Firebase stores Chicago local time as: 'YYYY-MM-DD HH:MM:SS'
    Convert to Notion-friendly UTC ISO: 'YYYY-MM-DDTHH:MM:SS+00:00'
    """
    s = (fb_str or "").strip()
    if not s:
        return ""
    dt_local = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CHI)
    dt_utc = dt_local.astimezone(UTC)
    return dt_utc.isoformat(timespec="seconds")


def notion_utc_iso_to_fb_local_str(iso: str) -> str:
    """
    Notion returns '...+00:00' (UTC). Convert to Chicago local string.
    """
    s = (iso or "").strip()
    if not s:
        return ""
    dt_utc = datetime.fromisoformat(s.replace("Z", "+00:00"))
    dt_local = dt_utc.astimezone(CHI)
    return dt_local.strftime("%Y-%m-%d %H:%M:%S")


def notion_success(msg: str, label: str = ""):
    if label == "":
        st.success(f"✅ {msg}")
    else:
        st.success(f"✅ {msg} ({label})")


def _pick_fab_db_url(run_class: str | None) -> str:
    if (run_class or "").lower() == "test":
        return st.secrets["notion"]["NOTION_FAB_TEST_DB_URL"]
    return st.secrets["notion"]["NOTION_FAB_DB_URL"]


# def get_page_url(notion, database_url: str, title: str):
#     database_id = get_id(database_url)
#     st.write(database_id)
#     results = notion.databases.query(
#         database_id=database_id,
#         filter={
#             "property": "title",  # make sure this matches your DB title property
#             "rich_text": {"contains": title},
#         },
#     )

#     pages = results.get("results", [])
#     if not pages:
#         return None

#     return pages[0]["url"]


def run_exists(run_no, id_token):
    res = firestore_get("runs", run_no, id_token)
    return "fields" in res


def compute_layer_progress(layer):
    all_chips = [
        ch
        for sub in layer.get("substeps", [])
        for ch in sub.get("chips", [])
    ]

    if not all_chips:
        return 0

    done_count = sum(1 for ch in all_chips if ch["status"] == "done")
    return int(100 * done_count / len(all_chips))




def build_steps_from_flow(flow):
    steps = []
    for layer in flow:
        steps.append(
            {
                "layer_name": layer["layer_name"],
                "progress": 0,
                "substeps": [
                    {
                        "name": sub.get("label", sub.get("name")),
                        "chips": [
                            {"name": chip["name"], "status": "pending"}
                            for chip in sub.get("chips", [])
                        ],
                    }
                    for sub in layer.get("substeps", [])
                ],
            }
        )
    return steps


# -------------------------------------------------
# 🔑 Status editor widget nonce (init ONCE)
# -------------------------------------------------
if "status_nonce" not in st.session_state:
    st.session_state["status_nonce"] = 0


st.set_page_config(page_title="Fab Tracker - Admin", page_icon="🛠", layout="wide")

# -----------------------------
# Design/fab uploader reset nonce
# -----------------------------
if "design_upload_nonce" not in st.session_state:
    st.session_state["design_upload_nonce"] = 0
if "fab_upload_nonce" not in st.session_state:
    st.session_state["fab_upload_nonce"] = 0


st.markdown(
    """
    <style>
    /* Sometimes the text is inside a span */
    [data-testid="stTabs"] button[role="tab"] * {
        font-size: 16px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------
# Init Flow in session_state
# ------------------------------------------------------------
if "flow" not in st.session_state:
    st.session_state["flow"] = build_default_flow(DEFAULT_FLOW)


# ------------------------------------------------------------
# 1. GOOGLE LOGIN
# ------------------------------------------------------------


if "user" not in st.session_state:

    client_id = st.secrets["google_oauth"]["client_id"]
    client_secret = st.secrets["google_oauth"]["client_secret"]

    redirect_uri = st.secrets["app"]["admin_redirect_uri"]

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

    # query_params = st.experimental_get_query_params()
    query_params = st.query_params


    if "code" not in query_params:
        # st.markdown(f"[Login with Google]({auth_url})")
        st.link_button("Login with Google", auth_url)
        st.stop()

    code = query_params["code"]

    token_res = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
      

    token_json = token_res.json()

    if "id_token" not in token_json:
        st.error(f"Google token exchange failed: {token_json}")
        st.stop()

    id_token = token_json["id_token"]


    user = firebase_sign_in_with_google(id_token, redirect_uri)

    email = user.get("email", "")
    if not email.endswith("@eeroq.com"):
        st.error("Unauthorized domain")
        st.stop()

    st.session_state["user"] = user
    st.session_state["login_time"] = time.time()

    # st.experimental_set_query_params()
    st.query_params.clear()
    st.rerun()




# ---- PAGE TITLE ----
# st.markdown("""
#     <h1 style="margin-top: -60px; margin-bottom: -40px;">
#         🛠️ Run Editor
#     </h1>
# """, unsafe_allow_html=True)

st.markdown("""
    <h1 style="margin-top: -100px; margin-bottom: 0px;">
        🛠️ Run Editor
    </h1>
""", unsafe_allow_html=True)

# user = st.session_state["user"]
# id_token = user["idToken"]
# user_email = user["email"]

user = st.session_state["user"]

# --- Auto-refresh token if expired (copy from viewer) ---
expires_in = int(user.get("expiresIn", "3600"))
login_time = st.session_state.get("login_time", time.time())

# Check if 55 minutes passed
if time.time() - login_time > 3300:  # 55 minutes
    refresh_token = user["refreshToken"]
    new_tokens = firebase_refresh_id_token(refresh_token)

    # Update session_state with new tokens
    user["idToken"] = new_tokens["id_token"]
    user["refreshToken"] = new_tokens["refresh_token"]
    user["expiresIn"] = new_tokens["expires_in"]
    st.session_state["user"] = user
    st.session_state["login_time"] = time.time()

# Always use updated token
id_token = user["idToken"]
user_email = user["email"]



st.sidebar.success("Logged in as: " + user_email)
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()

# ------------------------------------------------------------
# Fast preset loading (only once!)
# ------------------------------------------------------------
if "layer_presets" not in st.session_state:
    st.session_state["layer_presets"] = {}

if "active_preset" not in st.session_state:
    st.session_state["active_preset"] = {}

# Marker so we only load from Firestore once per login
if "layer_presets_loaded" not in st.session_state:
    st.session_state["layer_presets_loaded"] = False

load_layer_presets_once(st.session_state, id_token, DEFAULT_FLOW)



r1c1, r1c2 = st.columns(2)

# ------------------------------------------------------------
# 1. DELETE RUN (with confirmation)
# ------------------------------------------------------------
with r1c1:
    with st.expander("🗑 Delete Run", expanded=False):

        if "confirm_delete_run" not in st.session_state:
            st.session_state["confirm_delete_run"] = False


        with st.form("delete_run_form"):
    
            delete_class = st.radio(
                "Device Class",
                options=["Main", "Test"],
                horizontal=True,
                key="delete_run_class",
            )

            delete_id = st.text_input("Run No. to Delete (e.g., 001)")
            
            doc_id = f"{delete_class.lower()}_{delete_id.strip()}"

            # -------------------------------
            # First click: arm confirmation
            # -------------------------------
            if not st.session_state["confirm_delete_run"]:
                delete_btn = st.form_submit_button("🗑 Delete Run")

                if delete_btn:
                    if delete_id.strip() == "":
                        st.error("Please enter a valid Run ID.")
                    # elif not run_exists(delete_id, id_token):
                    #     st.error(f"Run '{delete_id}' does not exist.")

                    # snap = firestore_get("runs", doc_id, id_token)
                    # if not snap or not snap.get("exists", False):
                    #     st.error(f"{delete_class} run '{delete_id}' does not exist.")

                    snap = firestore_get("runs", doc_id, id_token)
                    if not snap or "fields" not in snap:
                        st.error(f"{delete_class} run '{delete_id}' does not exist.")


                    else:
                        st.session_state["confirm_delete_run"] = True
                        st.rerun()


            # -------------------------------
            # Second step: confirm / cancel
            # -------------------------------
            else:
                # ⚠️ WARNING MUST LIVE HERE
                st.warning(
                    f"⚠️ This will permanently delete Run '{delete_class}' '{delete_id}'. "
                    "This action cannot be undone."
                )

                c1, c2 = st.columns(2)

                with c1:
                    cancel_btn = st.form_submit_button("❌ Cancel")

                with c2:
                    confirm_btn = st.form_submit_button("🔥 Confirm Delete")

                if cancel_btn:
                    st.session_state["confirm_delete_run"] = False
                    st.info("Delete cancelled.")
                    st.rerun()

                if confirm_btn:

                    # -----------------------------------------
                    # ✅ Best-effort: archive all Notion pages for this run
                    # -----------------------------------------
                    try:
                        # run_doc = firestore_get("runs", delete_id, id_token)
                        run_doc = firestore_get("runs", doc_id, id_token)
                        meta_py = firestore_to_python((run_doc or {}).get("fields", {}).get("metadata", {})) or {}

                        # ---- helper: get value from kv-list (fab/design style) ----
                        def _kv_get(meta_list, key: str) -> str:
                            kl = key.strip().lower()
                            for it in (meta_list or []):
                                if (it.get("key") or "").strip().lower() == kl:
                                    return (it.get("value") or "").strip()
                            return ""

                        notion_page_ids = set()

                        # 1) FAB Notion URL -> derive page_id (Notion style: last path segment is page_id without dashes)
                        fab_list = meta_py.get("fab", [])
                        fab_url = _kv_get(fab_list, "Notion")
                        if fab_url:
                            try:
                                pid = get_id(fab_url)
                                if pid:
                                    notion_page_ids.add(pid)
                            except Exception as e:
                                st.warning(f"[DBG] Failed to parse Fab Notion URL (non-blocking): {e}")

                        # 1b) FAB child pages (write-once, authoritative)
                        fab_child_ids = None
                        for it in (fab_list or []):
                            if (it.get("key") or "").strip() == "Fab Child Page IDs":
                                fab_child_ids = it.get("value")
                                break

                        if isinstance(fab_child_ids, list):
                            for pid in fab_child_ids:
                                if isinstance(pid, str) and pid.strip():
                                    notion_page_ids.add(pid.strip())

                        # 2) Measurement fridge pages (canonical notion_page_id)
                        fridges = (meta_py.get("measure", {}) or {}).get("fridges", {}) or {}
                        if isinstance(fridges, dict):
                            for _uid, fr in fridges.items():
                                if not isinstance(fr, dict):
                                    continue
                                pid = (fr.get("notion_page_id") or "").strip()
                                if pid:
                                    notion_page_ids.add(pid)

                        # 3) Archive each page (best-effort; do not block run delete)
                        for pid in sorted(notion_page_ids):
                            try:
                                archive_page(
                                    notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                    page_id=pid,
                                    archived=True,
                                    clear_relations=False,
                                )

                                notion_success("Related Notion pages deleted(archived)")

                            except Exception as e:
                                st.warning(f"[DBG] Notion archive failed for page_id={pid} (non-blocking): {e}")

                        if notion_page_ids:
                            st.info(f"Archived {len(notion_page_ids)} Notion page(s) (best-effort).")

                    except Exception as e:
                        st.warning(f"[DBG] Notion cleanup step failed (non-blocking): {e}")


                    # code, msg = firestore_delete("runs", delete_id, id_token)
                    code, msg = firestore_delete("runs", doc_id, id_token)

                    if code in (200, 204):
                        # st.success(f"Run '{delete_id}' deleted successfully!")
                        st.success(f"{delete_class} run '{delete_id}' deleted successfully!")
                        st.session_state.pop("loaded_run", None)
                        st.session_state.pop("loaded_run_no", None)
                    else:
                        st.error(f"Failed to delete: {msg}")

                    st.session_state["confirm_delete_run"] = False
                    st.rerun()
                    # st.stop()



# ------------------------------------------------------------
# 0. NOTION TEMPLATE STATE (MUST LOAD BEFORE CREATE RUN)
# ------------------------------------------------------------
def load_notion_templates_once():
    """
    Ensure Notion template settings exist in session_state.
    This must run before Create Run so payload uses current template.

    Fab template currently owns:
    - Key feature
    """
    if "notion_templates" in st.session_state:
        return

    # ✅ minimal Fab-only template (write-once at creation)
    st.session_state["notion_templates"] = {
        "fab_create": {
            "default_key_feature": "",
        }
    }



# ✅ must be called before Create Run uses it
load_notion_templates_once()



# ------------------------------------------------------------
# 2. CREATE FABRICATION RUN  (single form)
# ------------------------------------------------------------
# st.subheader("🆕 Create Run")
with r1c2:
    with st.expander("🆕 Create Run", expanded=False):
       
        # tabs = st.tabs(["General", "Design", "Fab", "Package", "Measurement", "Notion"])
        tabs = st.tabs(["General", "Design", "Fab", "Package", "Measurement"])


        today_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # with st.form("create_run_form"):
        with tabs[0]:


            # ------------------------------------------------
            # Device Class (single-select)
            # ------------------------------------------------
            class_col1, class_col2 = st.columns([0.2,0.8])
            with class_col1:
                st.markdown("Device Class")
        
            run_class = st.radio(
                label=" ",
                options=["Main", "Test"],
                horizontal=True,
                key="create_run_class",
                label_visibility = "collapsed",
            )

            with class_col2:
                # Optional captions (pure UI)
                if run_class == "Main":
                    st.write("[Electron-on-helium device]")
                elif run_class == "Test":
                    st.write("[Non-electron-on-helium device still requires cooldown]")


            # ------------------------------------------------
            # Device Type (single-select)
            # ------------------------------------------------
            st.markdown("Device Type")

            fab_type_sel = st.radio(
                label=" ",
                options=["Resonator", "Microchannel", "Skywater", "Other"],
                horizontal=True,
                key="create_run_type",
                label_visibility = "collapsed",
            )

            if fab_type_sel == "Other":
                fab_type = st.text_input(
                    "Custom Type",
                    key="create_fab_type_custom",
                    placeholder="Enter custom type name",
                ).strip()
            else:
                fab_type = fab_type_sel
          


            col1, col2 = st.columns(2)

            with col1:
                created_date = st.text_input(
                    "Run Created (YYYY-MM-DD)",
                    value=today_str,
                    disabled=True,
                    key="create_run_created",
                )

                run_no = st.text_input(
                    "Run No. (e.g., 001)",
                    key="create_run_no",
                )

                device_name = st.text_input(
                    "Device Name",
                    key="create_run_device_name",
                )



            with col2:

                creator = st.text_input(
                    "Creator",
                    value=user_email,
                    disabled=True,
                    key="create_run_creator",
                )

                lotid_general = st.text_input(
                    "Lot ID",
                    "",
                    key="create_run_lotid",
                )


            submitted = st.button("Create Run")



            # -------------------------------------------
            # Build initial chip-centric package metadata
            # -------------------------------------------

            # ---- handle submit OUTSIDE the form ----
            if submitted:
                run_no = (run_no or "").strip()
                lotid_final  = (lotid_general or "").strip()

                if not run_no:
                    st.error("Run No. is required.")
                    st.stop()

                # optional: enforce numeric
                if not run_no.isdigit():
                    st.error("Run No. must be numeric (e.g., 001).")
                    st.stop()

                if not device_name.strip():
                    st.error("Device Name is required.")
                    st.stop()

                # If you want Lot ID required for Notion creation, not for run creation:
                # (keep as warning later)

                if not lotid_final:
                    st.error("Lot ID is required.")
                    st.stop()


                if not run_class:
                    st.error("Class is required.")
                    st.stop()

                if not fab_type:
                    st.error("Type is required.")
                    st.stop()

                # ------------------------------------------------
                # 🚫 HARD BLOCK: duplicate run within same class
                # ------------------------------------------------
                doc_id = f"{run_class.lower()}_{run_no}"
                snap = firestore_get("runs", doc_id, id_token=id_token)
                # if snap and snap.get("exists", False):
                if snap and snap.get("fields"):
                    st.error(f"{run_class} run '{run_no}' already exists. Please delete it first.")
                    st.stop()



                # ----------------------------
                # Create Notion page (Fab) on Create Run
                # ----------------------------
                st.session_state.setdefault("create_fab_notion_url", "")

                # Use Lot ID from General tab (simple + reliable)
                lotid_final = (lotid_general or "").strip()

                # Local only (don’t persist in session_state)
                notion_url = ""

                # best-effort: create Notion page (Fab)
                if lotid_final:
                    load_notion_templates_once()
                    tmpl = st.session_state.get("notion_templates", {}).get("fab_create", {})

                    # 🔑 FINAL properties dict (subprocess expects this exact shape)
                    properties = {
                        # auto-assigned identity
                        "No": int(run_no) if str(run_no).isdigit() else run_no,
                        "Name": device_name,
                        "Lot ID": lotid_final,
                    }


                    # ------------------------------------------------
                    # 🆕 Fab Type
                    # ------------------------------------------------
                    if fab_type:
                        properties["Type"] = fab_type

                    # ------------------------------------------------
                    # Fab Key feature (unchanged)
                    # ------------------------------------------------
                    fab_key_feature = (st.session_state.get("create_fab_key_feature", "") or "").strip()
                    if fab_key_feature:
                        properties["Key feature"] = fab_key_feature


                    # # initial status (optional, but matches your old behavior)
                    properties["Status"] = ["In progress"]

                    payload = {
                        "stage": "Fab",
                        "run_no": run_no,
                        "properties": properties,   # ✅ BACK TO WORKING CONTRACT
                    }

                    try:
                        result = create_fab_page(
                            notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                            # fab_db_url=st.secrets["notion"]["NOTION_FAB_DB_URL"],
                            fab_db_url=_pick_fab_db_url(run_class),
                            properties=properties,
                        )

                        notion_url = (result.get("url", "") or "").strip()

                        notion_success("Fab Notion page created")

                        if not notion_url:
                            st.warning(f"Run will be created, but Notion returned no url: {result}")
                    # except Exception as e:
                        # Do NOT block run creation if Notion fails
                        # st.warning(f"Run will be created, but Notion page creation failed: {e}")
                    except Exception as e:
                        import traceback
                        st.error("Notion creation error:")
                        st.code(traceback.format_exc())
                        st.write("Notion client module:", notion_client)
                        st.write("Notion client file:", inspect.getfile(notion_client))


                else:
                    st.warning("Lot ID is empty → skipping Notion page creation.")





                # 🔥 HARD RESET of Status Editor widget state (Create Run)
                for k in list(st.session_state.keys()):
                    if (
                        k.startswith("status_")
                        or k.startswith("prev_status_")
                        or k.startswith("upd_status_")
                        or k.startswith("chip_status_")
                    ):
                        st.session_state.pop(k, None)

                # (optional but safe) clear layer editor cache too
                st.session_state.pop("update_layers", None)

               # 🔑 1️⃣ Upgrade steps → ensure chip_uid + label exist
                # ensure_chip_ids(steps)
                flow = st.session_state["flow"]
                steps = build_steps_from_flow(flow)
                ensure_flow_ids(steps)

                # st.write("DEBUG Create Run steps:", steps)

                package_chip_meta = build_package_chip_meta(
                    steps,        # <-- steps created at Run creation
                    {}            # no previous metadata
                )

                measure_fridge_meta = build_measure_fridge_meta(steps, {})



                # 🔥 FINAL GUARANTEE — force ALL chips to pending
                for layer in steps:
                    for sub in layer.get("substeps", []):
                        for chip in sub.get("chips", []):
                            chip["status"] = "pending"
                            chip.pop("started_at", None)
                            chip.pop("completed_at", None)



                data = {
                    "run_no": run_no,
                    "device_name": device_name,
                    "creator": creator,
                    "created_date": created_date,
                    "class": run_class,
                    "steps": steps,
                    "metadata": {
                        # "design": design_meta,
                        # "fab": fab_meta,
                        "design": st.session_state.get("create_design_meta", []),
                        "fab": st.session_state.get("create_fab_meta", []),
                        # "package": package_meta,
                        "package": {
                            "chips":package_chip_meta,
                        },  
                        "measure": {
                            "fridges":measure_fridge_meta,
                        }
                    },
                }

                # ✅ Refresh design meta at submit-time (prevents stale empty strings)
                data["metadata"]["design"] = [
                    {"key": "Creator", "value": st.session_state.get("create_design_creator", "")},
                    {"key": "Verifier", "value": st.session_state.get("create_design_verifier", "")},
                    {"key": "Lotid", "value": lotid_final},
                    {"key": "Chip size (mm2)", "value": st.session_state.get("create_design_chip_size", "")},
                    {"key": "Completed", "value": ""},  # keep seed only; do NOT timestamp here
                    {"key": "File", "value": st.session_state.get("create_design_file_url", "")},
                    {"key": "FileId", "value": st.session_state.get("create_design_file_id", "")},
                    {"key": "FileName", "value": st.session_state.get("create_design_file_name", "")},
                    {"key": "Notion", "value": ""},     # design notion not created here
                    {"key": "Spec", "value": st.session_state.get("create_design_spec", "")},
                    {"key": "Notes", "value": st.session_state.get("create_design_notes", "")},
                ]


                for layer in steps:
                    for sub in layer.get("substeps", []):
                        for chip in sub.get("chips", []):
                            assert chip["status"] == "pending"


                # --- (INSIDE: if submitted:) ---
                # Put this AFTER: data = {...}
                # Put this BEFORE: firestore_set("runs", run_no, data, ...)

                # ✅ FORCE-INJECT Notion URL into Fab metadata list so it persists + shows in table
                if notion_url:
                    fab_list = data["metadata"].setdefault("fab", [])
                    for it in fab_list:
                        if isinstance(it, dict) and it.get("key") == "Notion":
                            it["value"] = notion_url
                            break
                    else:
                        fab_list.append({"key": "Notion", "value": notion_url})


                if lotid_final:
                    # Design metadata
                    design_list = data["metadata"].setdefault("design", [])
                    for it in design_list:
                        if it.get("key") == "Lotid":
                            it["value"] = lotid_final
                            break
                    else:
                        design_list.append({"key": "Lotid", "value": lotid_final})

                    # Fab metadata (optional but useful)
                    fab_list = data["metadata"].setdefault("fab", [])
                    for it in fab_list:
                        if it.get("key") == "Lotid":
                            it["value"] = lotid_final
                            break
                    else:
                        fab_list.append({"key": "Lotid", "value": lotid_final})


                # ✅ Persist template fields into Fab metadata (so later subprocess can read them)
                tmpl = st.session_state.get("notion_templates", {}).get("fab_create", {}) or {}

                # ---- Type ----
                default_type = (tmpl.get("default_type") or "").strip()
                if default_type:
                    fab_list = data["metadata"].setdefault("fab", [])
                    for it in fab_list:
                        if it.get("key") == "Type":
                            it["value"] = default_type
                            break
                    else:
                        fab_list.append({"key": "Type", "value": default_type})

                # ---- Key feature ----
                default_key_feature = (tmpl.get("default_key_feature") or "").strip()
                if default_key_feature:
                    fab_list = data["metadata"].setdefault("fab", [])
                    for it in fab_list:
                        if it.get("key") == "Key feature":
                            it["value"] = default_key_feature
                            break
                    else:
                        fab_list.append({"key": "Key feature", "value": default_key_feature})


                # firestore_set("runs", run_no, data, id_token=id_token)
                doc_id = f"{run_class.lower()}_{run_no}"

                firestore_set("runs", doc_id, data, id_token=id_token)

                st.success(f"Run '{run_no}' created successfully!")

                # -----------------------------------------
                # Clear Create Run session state (existing)
                # -----------------------------------------
                st.session_state.pop("create_design_file_url", None)
                st.session_state.pop("create_design_file_id", None)

                st.session_state.pop("create_fab_notion_url", None)
                st.session_state.pop("create_fab_meta", None)

                st.session_state.pop("create_fab_files", None)
                st.session_state.pop("create_fab_file_url", None)
                st.session_state.pop("create_fab_file_id", None)
                st.session_state.pop("create_fab_file_name", None)


        # ----------------- DESIGN TAB -----------------
        with tabs[1]:

            subtabs = st.tabs(["Flow", "Details"])

            with subtabs[1]:

                c1, c2 = st.columns(2)
                with c1:
                    st.text_input("Creator", "", key="create_design_creator")
                    st.text_input("Chip size (mm2)", "", key="create_design_chip_size")


                with c2:
                    st.text_input("Verifier", "", key="create_design_verifier")

                    # Persist attachment across reruns during Create Run
                    file_design = st.session_state.get("create_design_file_url", "")
                    file_design_id = st.session_state.get("create_design_file_id", "")

                    uploaded = st.file_uploader(
                        "Attach file",
                        type=None,  # optionally restrict e.g. ["pdf","zip","gds","dwg","dxf"]
                        key=f"create_design_file_upl_{st.session_state['design_upload_nonce']}",
                    )

                    replace_clicked = False

                    if file_design:
                        fname = st.session_state.get("create_design_file_name", "")
                        c1, c2, c3 = st.columns([3, 1, 1.5])

                        with c1:
                            st.caption(f"Attached: {fname}" if fname else "Attached:")

                        with c3:
                            replace_clicked = st.button(
                                "Replace",
                                key=f"create_design_file_replace_btn_{st.session_state.get('status_nonce', 0)}",
                            )


                    # if uploaded is not None:
                    #     if st.button(
                    #         "Upload",
                    #         key=f"create_design_file_upload_btn_{st.session_state.get('status_nonce', 0)}"
                    #     ):

                    has_existing = bool(file_design_id)  # or bool(file_design)

                    if (uploaded is not None) and (not has_existing):
                        if st.button(
                            "Upload",
                            key=f"create_design_file_upload_btn_{st.session_state.get('status_nonce', 0)}"
                        ):

                            # 🔒 prevent re-uploading the same file on every click
                            sig = (uploaded.name, uploaded.size)
                            last_sig = st.session_state.get("create_design_last_upload_sig")
                            last_id  = st.session_state.get("create_design_file_id")

                            if last_id and last_sig == sig:
                                st.info("This file is already uploaded.")
                            else:
                                out = upload_file_via_cleanroom_api(
                                    uploaded_file=uploaded,
                                    filename=uploaded.name,
                                    folder_id=st.secrets["app"]["drive_folder_id_design"],
                                )

                                if out.get("success"):
                                    st.session_state["create_design_file_url"] = out.get("url", "")
                                    st.session_state["create_design_file_id"] = out.get("id", "")
                                    st.session_state["create_design_file_name"] = uploaded.name   # ✅ ADD THIS LINE
                                    st.session_state["create_design_last_upload_sig"] = sig  # ✅ remember
                                    st.session_state["design_upload_nonce"] += 1  # ✅ reset uploader widget
                                    st.success("Uploaded via cleanroomLoggerAPI and linked.")
                                    st.rerun()
                                else:
                                    st.error(out.get("error", "Upload failed (no error message)."))

                    # ----------------------------
                    # Replace (upload new + trash old)
                    # ----------------------------
                    if replace_clicked:
                        if uploaded is None:
                            st.error("Select a new file first, then click Replace.")
                        else:
                            old_id = st.session_state.get("create_design_file_id", "")

                            out = upload_file_via_cleanroom_api(
                                uploaded_file=uploaded,
                                filename=uploaded.name,
                                folder_id=st.secrets["app"]["drive_folder_id_design"],
                            )

                            if out.get("success"):
                                new_id = out.get("id", "")

                                # Update run -> new file
                                st.session_state["create_design_file_url"] = out.get("url", "")
                                st.session_state["create_design_file_id"] = new_id
                                st.session_state["create_design_file_name"] = uploaded.name

                                # Trash old file only after new upload succeeds
                                if old_id and old_id != new_id:
                                    del_out = delete_file_via_cleanroom_api(file_id=old_id)
                                    if not del_out.get("success"):
                                        st.warning(
                                            "New file uploaded, but old file could not be trashed: "
                                            + str(del_out.get("error", "unknown error"))
                                        )

                                # Reset uploader only on success (clears selection)
                                cur_nonce = st.session_state.get("design_upload_nonce", 0)
                                st.session_state.pop(f"create_design_file_upl_{cur_nonce}", None)
                                st.session_state["design_upload_nonce"] = cur_nonce + 1

                                st.success("Replaced design file (old file moved to Trash).")
                                st.rerun()
                            else:
                                st.error(out.get("error", "Replace failed (no error message)."))



                    # Refresh from session_state after potential upload
                    file_design = st.session_state.get("create_design_file_url", "")
                    file_design_id = st.session_state.get("create_design_file_id", "")



                
                # spec = st.text_area("Specification", "")
                st.text_area("Specification", "", key="create_design_spec")

                # notes_design = st.text_area("Notes (design)", "", height=120)
                st.text_area("Notes (design)", "", key="create_design_notes", height=120)

            with subtabs[0]:
     
                flow_editor(layer_filter="Design", ui_mode = "flat")  # <- see note below

            completed = ""
            notion_design = ""
         
            file_design = st.session_state.get("create_design_file_url", "")
            file_design_id = st.session_state.get("create_design_file_id", "")
            file_design_name = st.session_state.get("create_design_file_name", "")

            design_meta = [
                {"key": "Creator", "value": st.session_state.get("create_design_creator", "")},
                {"key": "Verifier", "value": st.session_state.get("create_design_verifier", "")},
                {"key": "Lotid", "value": lotid_general},
                {"key": "Chip size (mm2)", "value": st.session_state.get("create_design_chip_size", "")},
                {"key": "Completed", "value": completed},

                {"key": "File", "value": file_design},
                {"key": "FileId", "value": file_design_id},
                {"key": "FileName", "value": file_design_name},

                {"key": "Notion", "value": notion_design},
                {"key": "Spec", "value": st.session_state.get("create_design_spec", "")},
                {"key": "Notes", "value": st.session_state.get("create_design_notes", "")},
            ]


            st.session_state["create_design_meta"] = design_meta



        # ----------------- FAB TAB -----------------
        with tabs[2]:
            subtabs = st.tabs(["Flow", "Details"])
            with subtabs[1]:

                c1, c2 = st.columns(2)
                with c1:
                    pic_fab = st.text_input("Owner", "")
                with c2:
                    substrate = st.text_input("Substrate", "")
                ca, cb = st.columns(2)
                with ca:
                    process = st.text_input("Process (e.g. Top-down)", "")
                with cb:
                    n_chips = st.text_input("\# of chips", "")


                fab_key_feature = st.text_area(
                    "Key feature",
                    value="",
                    key="create_fab_key_feature",
                    height=80,
                    placeholder='',
                ).strip()


                notes_fab = st.text_area("Notes (fab)", "")

                # ----------------------------
                # FAB file attach (multi-file)
                # ----------------------------

                # Ensure list exists
                if "create_fab_files" not in st.session_state:
                    st.session_state["create_fab_files"] = []

                fab_files = st.session_state.get("create_fab_files", [])

                uploaded_fab = st.file_uploader(
                    "Attach fab file",
                    type=None,
                    key=f"create_fab_file_upl_{st.session_state.get('fab_upload_nonce', 0)}",
                )

                # Always show current attachments
                # st.markdown("##### 📎 Attachments")
                if not fab_files:
                    st.caption("No attachments.")
                else:
                    for i, f in enumerate(fab_files, start=1):
                        st.write(f"{i}. {f.get('name', '')}")

                # Select which one to replace (if any exist)
                replace_idx = None
                if fab_files:
                    replace_idx = st.selectbox(
                        "Select file to replace",
                        options=list(range(len(fab_files))),
                        format_func=lambda i: f"{i+1}. {fab_files[i].get('name','')}",
                        key=f"create_fab_replace_sel_{st.session_state.get('status_nonce', 0)}",
                    )

                # Buttons
                cbtn1, cbtn2 = st.columns([1, 1])
                with cbtn1:
                    upload_clicked = st.button(
                        "Upload (Add)",
                        key=f"create_fab_file_upload_btn_{st.session_state.get('status_nonce', 0)}",
                    )
                with cbtn2:
                    replace_clicked_fab = st.button(
                        "Replace selected",
                        disabled=not bool(fab_files),
                        key=f"create_fab_file_replace_btn_{st.session_state.get('status_nonce', 0)}",
                    )

                # ----------------------------
                # Upload (Add) — always allowed
                # ----------------------------
                if upload_clicked:
                    if uploaded_fab is None:
                        st.error("Select a file first, then click Upload (Add).")
                    else:
                        sig = (uploaded_fab.name, uploaded_fab.size)
                        last_sig = st.session_state.get("create_fab_last_upload_sig")

                        if last_sig == sig:
                            st.info("This file is already uploaded.")
                        else:
                            out = upload_file_via_cleanroom_api(
                                uploaded_file=uploaded_fab,
                                filename=uploaded_fab.name,
                                folder_id=st.secrets["app"]["drive_folder_id_fab"],
                            )

                            if out.get("success"):
                                chi = pytz.timezone("America/Chicago")
                                now_chi = datetime.now(chi).strftime("%Y-%m-%d %H:%M:%S")

                                st.session_state["create_fab_files"].append({
                                    "url": out.get("url", ""),
                                    "id":  out.get("id", ""),
                                    "name": uploaded_fab.name,
                                    "ts": now_chi,
                                })

                                # keep legacy primary pointing to latest
                                last = st.session_state["create_fab_files"][-1]
                                st.session_state["create_fab_file_url"] = last.get("url", "")
                                st.session_state["create_fab_file_id"] = last.get("id", "")
                                st.session_state["create_fab_file_name"] = last.get("name", "")

                                st.session_state["create_fab_last_upload_sig"] = sig

                                # Reset uploader only on success
                                cur_nonce = st.session_state.get("fab_upload_nonce", 0)
                                st.session_state.pop(f"create_fab_file_upl_{cur_nonce}", None)
                                st.session_state["fab_upload_nonce"] = cur_nonce + 1

                                st.success("Uploaded (added).")
                                st.rerun()
                            else:
                                st.error(out.get("error", "Upload failed (no error message)."))

                # -----------------------------------------
                # Replace selected — upload new + trash old
                # -----------------------------------------
                if replace_clicked_fab:
                    if uploaded_fab is None:
                        st.error("Select a new file first, then click Replace selected.")
                    elif replace_idx is None:
                        st.error("No existing file selected to replace.")
                    else:
                        fab_files = st.session_state.get("create_fab_files", [])
                        old_id = fab_files[replace_idx].get("id", "")

                        out = upload_file_via_cleanroom_api(
                            uploaded_file=uploaded_fab,
                            filename=uploaded_fab.name,
                            folder_id=st.secrets["app"]["drive_folder_id_fab"],
                        )

                        if out.get("success"):
                            chi = pytz.timezone("America/Chicago")
                            now_chi = datetime.now(chi).strftime("%Y-%m-%d %H:%M:%S")

                            new_id = out.get("id", "")

                            # overwrite selected slot
                            fab_files[replace_idx] = {
                                "url": out.get("url", ""),
                                "id":  new_id,
                                "name": uploaded_fab.name,
                                "ts": now_chi,
                            }
                            st.session_state["create_fab_files"] = fab_files

                            # Trash old only after new upload succeeds
                            if old_id and old_id != new_id:
                                del_out = delete_file_via_cleanroom_api(file_id=old_id)
                                if not del_out.get("success"):
                                    st.warning(
                                        "New file uploaded, but old file could not be trashed: "
                                        + str(del_out.get("error", "unknown error"))
                                    )

                            # keep legacy primary pointing to latest
                            last = st.session_state["create_fab_files"][-1] if st.session_state["create_fab_files"] else {}
                            st.session_state["create_fab_file_url"] = last.get("url", "")
                            st.session_state["create_fab_file_id"] = last.get("id", "")
                            st.session_state["create_fab_file_name"] = last.get("name", "")

                            # Reset uploader only on success
                            cur_nonce = st.session_state.get("fab_upload_nonce", 0)
                            st.session_state.pop(f"create_fab_file_upl_{cur_nonce}", None)
                            st.session_state["fab_upload_nonce"] = cur_nonce + 1

                            st.success("Replaced selected file (old file moved to Trash).")
                            st.rerun()
                        else:
                            st.error(out.get("error", "Replace failed (no error message)."))

            
            with subtabs[0]:
                flow_editor(layer_filter="Fabrication", ui_mode = 'flat')


            fabin = ""
            fabout = ""
            # ✅ Don't rely on session_state for persistence; Create Run handler will inject.
            notion_fab = ""

            fab_meta = [
                {"key": "Owner", "value": pic_fab},
                {"key": "Process", "value": process},
                {"key": "Substrate", "value": substrate},
                {"key": "Type", "value": fab_type},
                {"key": "Key feature", "value": fab_key_feature},
                {"key": "Qty chips", "value": n_chips},
                {"key": "Fabin", "value": fabin},
                {"key": "Fabout", "value": fabout},
                {"key": "Notes", "value": notes_fab},
                {"key": "Notion", "value": notion_fab},
                {"key": "File",     "value": st.session_state.get("create_fab_file_url", "")},
                {"key": "FileId",   "value": st.session_state.get("create_fab_file_id", "")},
                {"key": "FileName", "value": st.session_state.get("create_fab_file_name", "")},
            ]

            # ✅ Persist all attachments in serializer-safe flat keys
            fab_files = st.session_state.get("create_fab_files", [])
            for idx, f in enumerate(fab_files, start=1):
                fab_meta.extend([
                    {"key": f"FileId_{idx}",   "value": f.get("id", "")},
                    {"key": f"FileName_{idx}", "value": f.get("name", "")},
                ])

            st.session_state["create_fab_meta"] = fab_meta


        # ----------------- PACKAGE TAB -----------------
        with tabs[3]:
            subtabs = st.tabs(["Flow", "Details"])

            with subtabs[1]:
     
                st.info(
                    "📦 Package metadata is chip-centric and edited per chip after run creation.\n\n"
                    # "• Add/rename chips in Package flow\n"
                    # "• Update PCB/Bond/Delivery per chip\n"
                    # "• Viewer shows one row per chip\n"
                )
            with subtabs[0]:
                flow_editor(layer_filter="Package", ui_mode = "flat")

        # ----------------- MEASUREMENT TAB -----------------
        with tabs[4]:
            # left, right = st.columns([1, 1])
            subtabs = st.tabs(["Flow", "Details"])

            with subtabs[1]:
                st.info("📈 Measurement metadata is fridge-centric and edited per fridge after run creation.")

            with subtabs[0]:
                flow_editor(layer_filter="Measurement", ui_mode = "flat")




r2c1, r2c2 = st.columns(2)

# ------------------------------------------------------------
# 3. UPDATE EXISTING RUN
# ------------------------------------------------------------
with r2c1:
    with st.expander("🛠 Update Run", expanded=False):

        def iter_layers_filtered(layers, layer_filter=None):
            if not layer_filter:
                return list(enumerate(layers))
            want = layer_filter.strip().lower()
            return [(i, l) for i, l in enumerate(layers) if (l.get("layer_name") or "").strip().lower() == want]


        # ----------------------------
        # LOAD RUN (INSIDE THE FORM)
        # ----------------------------
        with st.form("update_run_form"):
            
            update_class = st.radio(
                "Device Class",
                options=["Main", "Test"],
                horizontal=True,
                key="update_run_class",
            )

            run_to_load = st.text_input("Enter Run No. to Load (e.g., 001)")
            load_btn = st.form_submit_button("Load Run")

            if load_btn:

                doc_id = f"{update_class.lower()}_{run_to_load.strip()}"

                # 1. clear stale cache BEFORE saving new run
                st.session_state.pop("update_layers", None)
                st.session_state.pop("update_meta", None)   # 🔥 ADD THIS LINE

                # 🔒 RESET progress history (CRITICAL)
                st.session_state.pop("prev_fab_progress", None)
                st.session_state.pop("prev_design_progress", None)

                # run_data = firestore_get("runs", run_to_load, id_token)
                run_data = firestore_get("runs", doc_id, id_token)

                if "fields" not in run_data:
                    st.error("Run not found.")
                else:
                    fields = run_data['fields']
                    # 🔒 HARD GUARANTEE: metadata must exist
                    if "metadata" not in fields:
                        fields["metadata"] = {
                            "mapValue": {
                                "fields": {
                                    "design":  {"arrayValue": {"values": []}},
                                    "fab":     {"arrayValue": {"values": []}},
                                    "package": {"arrayValue": {"values": []}},
                                    "measure": {"arrayValue": {"values": []}},
                                }
                            }
                        }

                    # 2. save new run
                    st.session_state["loaded_run"] = run_data
                    # st.session_state["loaded_run_no"] = run_to_load
                    st.session_state["loaded_run_no"] = (
                        fields.get("run_no", {}).get("stringValue", run_to_load)
                    )


                    # 🔑 ADD THESE (identity)
                    st.session_state["loaded_run_class"] = update_class
                    st.session_state["loaded_run_doc_id"] = doc_id

                    # ✅ cache run-level device name for Notion / UI
                    st.session_state["loaded_device_name"] = (
                        fields.get("device_name", {}).get("stringValue", "")
                    )


                    # ----------------------------
                    # Reset Update-Design uploader state on run load
                    # ----------------------------
                    st.session_state["upd_design_upload_nonce"] = st.session_state.get("upd_design_upload_nonce", 0) + 1
                    st.session_state["upd_design_last_sig"] = None


                    # ====================================================
                    # 🔑 Option A — reset Package/Measurement chip context on reload
                    # ====================================================
                    st.session_state.pop("pkg_prev_chip_uid", None)
                    st.session_state["pkg_chip_nonce"] = st.session_state.get("pkg_chip_nonce", 0) + 1
                    st.session_state.pop("meas_prev_fridge_uid", None)
                    st.session_state["meas_fridge_nonce"] = st.session_state.get("meas_fridge_nonce", 0) + 1

                    # (keep existing invalidation if you already added it)
                    st.session_state["pkg_nonce"] = st.session_state.get("pkg_nonce", 0) + 1
                    st.session_state["meas_nonce"] = st.session_state.get("meas_nonce", 0) + 1

                    st.success("Run loaded!")
                    st.session_state["status_nonce"] = st.session_state.get("status_nonce", 0) + 1

                    st.rerun()





        # FORM ENDS HERE.  NO BUTTONS ALLOWED ABOVE THIS LINE.
        # ----------------------------
        # SHOW EDITORS ONLY IF LOADED
        # ----------------------------
        if "loaded_run" not in st.session_state or "loaded_run_no" not in st.session_state:
            st.info("Load a run to edit.")
        else:
            run = st.session_state["loaded_run"]
            loaded_run_no = st.session_state["loaded_run_no"]
            loaded_run_doc_id = st.session_state["loaded_run_doc_id"]
            fields = run["fields"]

            # 👇 EVERYTHING BELOW MUST BE INDENTED under this else:

            # ------------------------------------------------------------
            # ENSURE update_layers EXISTS (same invariant as Package)
            # ------------------------------------------------------------
            if "update_layers" not in st.session_state:
                st.session_state["update_layers"] = firestore_to_python(
                    fields.get("steps", [])
                )

            update_layers = st.session_state["update_layers"]


            icons = ["🎨", "⚡", "𓇲", "📈"]

            # ----------------------------------------------------
            # INITIALIZE METADATA CACHE (ONCE PER RUN LOAD)
            # ----------------------------------------------------
            # if "update_meta" not in st.session_state:
            if "update_meta" not in st.session_state or not st.session_state["update_meta"]:

                # meta_fields = fields["metadata"]["mapValue"]["fields"]
                meta_fields = fields.get("metadata", {}).get("mapValue", {}).get("fields", {})


                pkg_raw = firestore_to_python(meta_fields.get("package", {}))
                
                # ✅ Package-style: drill into measure.fridges.fields and convert
                meas_fridges_fields = (
                    meta_fields
                        .get("measure", {})
                        .get("mapValue", {})
                        .get("fields", {})
                        .get("fridges", {})
                        .get("mapValue", {})
                        .get("fields", {})
                )

                meas_fridges_py = {
                    uid: firestore_to_python(v)
                    for uid, v in meas_fridges_fields.items()
                }

                st.session_state["update_meta"] = {
                    "design": normalize_meta(firestore_to_python(meta_fields.get("design", []))),
                    "fab": normalize_meta(firestore_to_python(meta_fields.get("fab", []))),
                    "package": pkg_raw if isinstance(pkg_raw, dict) else {},
                    # "measure": {"fridges": meas_fridges_py},   # ✅ single source of truth
                }
                

                # 🔑 Measurement: rebuild from flow (IDENTICAL to Package logic)
                st.session_state["update_meta"]["measure"] = {
                    "fridges": build_measure_fridge_meta(
                        update_layers,                # ✅ SAME source as Package
                        meas_fridges_py
                    )
                }

                # 🔒 Prune Measurement fridges using SAME flow source
                current_flow_fridges = {
                    sub.get("fridge_uid")
                    for layer in update_layers
                    if layer.get("layer_name") == "Measurement"
                    for sub in layer.get("substeps", [])
                    if sub.get("fridge_uid")
                }

                st.session_state["update_meta"]["measure"]["fridges"] = {
                    uid: meta
                    for uid, meta in st.session_state["update_meta"]["measure"]["fridges"].items()
                    if uid in current_flow_fridges
                }


                # -------------------------------------------------
                # 🔒 Snapshot cooldown_start baseline ONCE per run load
                #     (transition guard for Measurement Notion logic)
                # -------------------------------------------------
                for _uid, _m in st.session_state["update_meta"].get("measure", {}).get("fridges", {}).items():
                    _m = _m or {}

                    # Find the cooldown_start key robustly (no guessing exact key name)
                    start_key = next(
                        (k for k in _m.keys()
                         if ("cooldown" in k.lower() and "start" in k.lower())),
                        None
                    )

                    prev_val = (_m.get(start_key, "") if start_key else "") or ""
                    st.session_state[f"prev_meas_cooldown_start_{loaded_run_doc_id}_{_uid}"] = prev_val



                # 🔒 Ensure Fabin / Fabout rows exist ONCE
                st.session_state["update_meta"]["fab"] = ensure_kv_rows(
                    st.session_state["update_meta"]["fab"],
                    ["Fabin", "Fabout"]
                )


            st.session_state.setdefault("upd_design_upload_nonce", 0)
            st.session_state.setdefault("upd_design_last_sig", None)

            st.session_state.setdefault("upd_fab_upload_nonce", 0)
            st.session_state.setdefault("upd_fab_last_sig", None)


           
            def render_status_editor(*, layers_py, fields, loaded_run_doc_id, id_token, target_layer=None, key_prefix=""):
                icons = ["🎨", "⚡", "𓇲", "📈"]
                run_id = loaded_run_doc_id or "none"

                # ------------------------------------------
                # 🔒 Reset all status locks if requested
                # ------------------------------------------
                if st.session_state.get("_reset_locks"):
                    for k in list(st.session_state.keys()):
                        if "_lock_" in k:
                            st.session_state[k] = False

                    st.session_state["_reset_locks"] = False


                def iter_layers_filtered(layers, layer_filter=None):
                    if not layer_filter:
                        return list(enumerate(layers))
                    want = layer_filter.strip().lower()
                    return [(i, l) for i, l in enumerate(layers) if (l.get("layer_name") or "").strip().lower() == want]

                for i, layer in iter_layers_filtered(layers_py, layer_filter=target_layer):
                    # with st.expander(f"{icons[i]} {layer['layer_name']}", expanded=False):
                    # ----------------------------
                    # Measurement fridge display names
                    # ----------------------------
                    fridge_display = {}
                    if layer["layer_name"].lower() == "measurement":
                        from collections import defaultdict
                        substeps = layer["substeps"]

                        ordered = []
                        for sub in substeps:
                            uid = sub.get("fridge_uid")
                            label = sub.get("label", sub.get("name", "Unknown"))
                            if uid:
                                ordered.append((uid, label))

                        by_label = defaultdict(list)
                        for uid, label in ordered:
                            by_label[label].append(uid)

                        for label, uids in by_label.items():
                            if len(uids) == 1:
                                fridge_display[uids[0]] = label
                            else:
                                for idx, uid in enumerate(uids, start=1):
                                    fridge_display[uid] = f"{label} ({idx})"

                ncols = 5
                cols = st.columns(ncols)
                for j, sub in enumerate(layer["substeps"]):
                    sub_uid = sub.get("chip_uid") or sub.get("fridge_uid") or j
                    col = cols[j % ncols]
                    with col:
                        if layer["layer_name"].lower() == "measurement":
                            title = fridge_display.get(
                                sub.get("fridge_uid"),
                                sub.get("label", sub.get("name", "Unknown"))
                            )
                        else:
                            title = sub.get("label", sub.get("name", "Unknown"))

                        # st.markdown(f"##### {title}")
                        # ------------------------------------------
                        # 🔒 Substep Lock Checkbox
                        # ------------------------------------------
                        # lock_key = f"{key_prefix}_lock_{run_id}_{layer_norm}_{sub_uid or j}"
                        lock_key = f"{key_prefix}_lock_{run_id}_{sub_uid}"


                        # default unchecked
                        if lock_key not in st.session_state:
                            st.session_state[lock_key] = False
                        # if st.session_state.get("_reset_locks"):
                        #     st.session_state[lock_key] = False
                        # elif lock_key not in st.session_state:
                        #     st.session_state[lock_key] = False



                        lock_col1, lock_col2 = st.columns([2, 1])

                        with lock_col1:
                            st.markdown(f"###### {title}")

                        with lock_col2:
                            st.checkbox("✏️",
                                key=lock_key,
                                label_visibility="collapsed",
                            )

                        is_unlocked = st.session_state.get(lock_key, False)



                        for k, ch in enumerate(sub["chips"]):

                            layer_norm = (layer.get("layer_name") or "").strip().lower()

                            # UID-stable keys to prevent Streamlit state inheritance when a substep is deleted/reordered
                            if layer_norm == "measurement":
                                sub_uid = (sub.get("fridge_uid") or "").strip()
                            elif layer_norm == "package":
                                sub_uid = (sub.get("chip_uid") or "").strip()
                            else:
                                sub_uid = ""

                            ch_name = (ch.get("name") or f"chip{k}").strip().lower().replace(" ", "_")

                            if sub_uid:
                                widget_key = f"{key_prefix}_status_{run_id}_{layer_norm}_{sub_uid}_{ch_name}"
                            else:
                                widget_key = f"{key_prefix}_status_{run_id}_{i}_{j}_{k}"

                            prev_key = f"prev_{widget_key}"


                            if prev_key in st.session_state and st.session_state[prev_key] == ch.get("status"):
                                old_status = st.session_state[prev_key]
                            else:
                                old_status = ch.get("status", "pending")

                            chip_name_norm = (ch.get("name") or "").strip().lower()
                            chip_type = (ch.get("type") or "").strip().lower()
                            layer_l = layer["layer_name"].strip().lower()

                            is_delivery = (layer_l == "package") and ((chip_type == "delivery") or (chip_name_norm == "delivery"))
                            is_storage  = (layer_l == "measurement") and ((chip_type == "storage") or (chip_name_norm == "storage"))

                            if is_delivery:
                                status_options = ["pending", "delivery#1", "delivery#2", "delivery#3", "delivery#4", "delivery#5"]
                            elif is_storage:
                                status_options = ["pending", "store#1", "store#2", "store#3", "store#4", "store#5"]
                            else:
                                # status_options = ["pending", "in_progress", "done"]
                                status_options = ["pending", "in_progress", "done", "terminate"]


                            # new_status = st.selectbox(
                            #     ch["name"],
                            #     status_options,
                            #     index=status_options.index(old_status) if old_status in status_options else 0,
                            #     key=widget_key,
                            # )


                            new_status = st.selectbox(
                                ch["name"],
                                status_options,
                                index=status_options.index(old_status) if old_status in status_options else 0,
                                key=widget_key,
                                disabled=not is_unlocked,   # 🔒 LOCK LOGIC
                            )


                            if old_status != new_status:
                                st.session_state["last_edited_layer"] = layer["layer_name"].lower()

                            st.session_state[prev_key] = new_status
                            chip_ref = layer["substeps"][j]["chips"][k]
                            chip_ref["status"] = new_status

                            chi = pytz.timezone("America/Chicago")
                            now_chi = datetime.now(chi).strftime("%Y-%m-%d %H:%M:%S")

                            if layer["layer_name"].strip().lower() == "measurement":
                                uid_for_dates = (sub.get("fridge_uid") or "").strip()
                                if not uid_for_dates:
                                    st.error(f"Measurement substep '{title}' is missing fridge_uid — cannot update cooldown timestamps.")
                                    continue
                            else:
                                uid_for_dates = (sub.get("chip_uid") or "").strip()


                            handle_chip_status_change(
                                chip_ref=chip_ref,
                                old_status=old_status,
                                new_status=new_status,
                                layer_name=layer["layer_name"],
                                chip_name=ch.get("name"),
                                chip_uid=uid_for_dates,
                                update_meta=st.session_state["update_meta"],
                                # run_no=loaded_run_no,
                                loaded_run_doc_id=loaded_run_doc_id,
                                id_token=id_token,
                                now_chi=now_chi,
                            )

                            if (ch.get("name") or "").strip().lower() == "cooldown":

                                # ✅ Use our own "previous" value, not old_status (which can be unreliable on reruns)
                                fridge_uid = uid_for_dates
                                prev_cool_key = f"prev_meas_cooldown_{loaded_run_doc_id}_{fridge_uid}"

                                prev_s = (st.session_state.get(prev_cool_key) or "pending").strip().lower()
                                cur_s  = (new_status or "").strip().lower()

                                # update immediately so we don't retrigger on the next rerun
                                st.session_state[prev_cool_key] = cur_s

                if st.session_state.get("_reset_locks"):
                    st.session_state["_reset_locks"] = False



            def _get_meta_val(meta_list, key: str) -> str:
                key_l = key.strip().lower()
                for it in (meta_list or []):
                    if (it.get("key") or "").strip().lower() == key_l:
                        return (it.get("value") or "").strip()
                return ""


            def _get_meas_fridge_meta(update_meta: dict, fridge_uid: str) -> dict:
                return (
                    (update_meta or {})
                    .get("measure", {})
                    .get("fridges", {})
                    .get(fridge_uid, {})
                )


            def _pick_meas_db_url(fridge_label: str) -> str:
                lab = (fridge_label or "").strip().lower()
                notion_sec = st.secrets.get("notion", {})

                if "ice" in lab:       # "ICEOxford"
                    return (notion_sec.get("NOTION_MEAS_DB_URL_ICEOXFORD") or "").strip()
                if "blue" in lab:      # "Bluefors"
                    return (notion_sec.get("NOTION_MEAS_DB_URL_BLUEFORS") or "").strip()
                return ""


            def _pick_meas_relation_prop(*, fridge_label: str, rel_key: str) -> str:
                """
                rel_key: logical relation name you use in code, e.g.
                  - "main_device"
                  - "test_device"
                Returns the exact Notion property name for that DB (case sensitive).
                """
                lab = (fridge_label or "").strip().lower()

                # Per-DB naming differences (case-sensitive in Notion)
                if "blue" in lab:
                    prop_map = {
                        "main_device": "Main device",
                        "test_device": "Test device",
                    }
                else:
                    # default: ICEOxford (and anything else)
                    prop_map = {
                        "main_device": "Main Device",
                        "test_device": "Test Device",
                    }

                # If you pass an unknown rel_key, fail loudly (better than silently doing nothing)
                if rel_key not in prop_map:
                    raise ValueError(f"Unknown rel_key for measurement relation: {rel_key}")

                return prop_map[rel_key]



            # -------------------------------
            # Notion sync (Fab → Notion props)
            # -------------------------------
            FAB_TO_NOTION_PROPS = {
                "Substrate": "Substrate",
                "Qty chips": "# of chips",
                "FABIN": "FABIN",
                "FABOUT": "FABOUT",
                "Notes": "Notes",
                "Type": "Type",
                "Key feature": "Key feature"
            }

            def _build_fab_notion_props(update_meta: dict) -> dict:
                """
                Build Notion properties dict from update_meta['fab'] meta_list.
                Only mirrors non-empty values; does NOT compute timestamps.
                """
                fab_list = (update_meta or {}).get("fab", [])
                props = {}

                # -------------------------------------------------
                # FABIN / FABOUT:
                # - empty  -> sentinel date (1970-01-01)
                # - non-empty -> date-only for Notion
                # -------------------------------------------------
                for meta_key, notion_prop in FAB_TO_NOTION_PROPS.items():
                    v = _get_meta_val(fab_list, meta_key)

                    if notion_prop in ("FABIN", "FABOUT"):
                        if v not in ("", None):
                            props[notion_prop] = str(v).split(" ")[0]  # date-only
                        else:
                            props[notion_prop] = "1970-01-01"
                        continue

                    # keep existing behavior for all other props: non-empty only
                    if v not in ("", None):
                        props[notion_prop] = v

                # -------------------------------------------------
                # Derived: Chip ID (text property)
                # Only if BOTH Design Lotid and Fab Qty chips exist.
                # Chip ID format: <LOTID>_C01, _C02, ...
                # -------------------------------------------------
                lotid = _get_meta_val((update_meta or {}).get("design", []), "Lotid")
                qty_raw = _get_meta_val(fab_list, "Qty chips")

                lotid = (lotid or "").strip()

                n_chips = None
                if qty_raw not in ("", None):
                    try:
                        n_chips = int(str(qty_raw).strip())
                    except Exception:
                        digits = "".join(ch for ch in str(qty_raw) if ch.isdigit())
                        n_chips = int(digits) if digits else None

                if lotid and n_chips and n_chips > 0:
                    chip_ids = [f"{lotid}_C{i:02d}" for i in range(1, n_chips + 1)]
                    props["Chip ID"] = "\n".join(chip_ids)

                # st.write(f"property: {props}")

                # ------------------------------------------------------------
                # 🆕 Derive Fab Status from latest completed fabrication chip
                # ------------------------------------------------------------
                layers = st.session_state.get("update_layers", []) or []

                latest_name = None
                latest_time = None

                for layer in layers:
                    if (layer.get("layer_name") or "").strip().lower() != "fabrication":
                        continue

                    for sub in layer.get("substeps", []) or []:
                        for chip in sub.get("chips", []) or []:
                            ts = (chip.get("completed_at") or "").strip()
                            if not ts:
                                continue

                            if latest_time is None or ts > latest_time:
                                latest_time = ts
                                latest_name = chip.get("name")

                # Only update if at least one chip is completed
                if latest_name:
                    props["Status"] = [latest_name]  # or latest_name depending on property type
                else:
                    props["Status"] = ["In progress"]


                return props


            def save_full_run(
                *,
                notion_source: str | None = None,
                notion_stage: str | None = None,
            ):

                # ------------------------------------------------------------
                # ✅ Derive Notion sync flags from caller intent
                # (exactly preserves old behavior)
                # ------------------------------------------------------------
                sync_fab_notion_lotid = False
                sync_fab_notion_fields = False
                sync_measure_notion = False
                sync_pkg_bond_to_fab_notion = False   # ← ADD THIS


                if notion_source is not None:
                    if notion_source not in ("status_save", "details_save", "details_override"):
                        raise RuntimeError(f"Notion side-effects blocked (source={notion_source})")

                    stage = (notion_stage or "").strip().lower()

                    if stage == "design":
                        sync_fab_notion_lotid = True
                        sync_fab_notion_fields = True

                    elif stage == "fabrication":
                        sync_fab_notion_fields = True

                    elif stage == "package":           # ← ADD THIS
                        sync_pkg_bond_to_fab_notion = True

                    elif stage == "measurement":
                        sync_measure_notion = True

                layers = st.session_state.get("update_layers")
                if not layers:
                    st.error("No run loaded (update_layers missing).")
                    return

                # ------------------------------------------------------------
                # Measurement: fridge_uid -> label (from Measurement flow)
                # Used by create/reset/date-range AND Bluefors chip sync
                # ------------------------------------------------------------
                fridge_label = {}
                for layer in (st.session_state.get("update_layers") or []):
                    if (layer.get("layer_name") or "").strip().lower() != "measurement":
                        continue
                    for sub in (layer.get("substeps", []) or []):
                        uid = sub.get("fridge_uid")
                        if not uid:
                            continue
                        fridge_label[uid] = sub.get("label") or sub.get("name") or "Measurement"


                # ------------------------------------------------------------
                # Measurement fridge captions: Bluefors (1), Bluefors (2), ...
                # Derived from current flow order (viewer-consistent)
                # ------------------------------------------------------------
                ordered_uids = []
                base_labels = []

                for layer in (st.session_state.get("update_layers") or []):
                    if (layer.get("layer_name") or "").strip().lower() != "measurement":
                        continue
                    for sub in layer.get("substeps", []) or []:
                        uid = sub.get("fridge_uid")
                        if not uid:
                            continue
                        ordered_uids.append(uid)
                        base_labels.append(
                            sub.get("label") or sub.get("name") or "Measurement"
                        )

                label_counts = {}
                for lbl in base_labels:
                    label_counts[lbl] = label_counts.get(lbl, 0) + 1

                label_indices = {}
                fridge_display_label = {}

                for uid, lbl in zip(ordered_uids, base_labels):
                    if label_counts[lbl] > 1:
                        label_indices[lbl] = label_indices.get(lbl, 0) + 1
                        fridge_display_label[uid] = f"{lbl} ({label_indices[lbl]})"
                    else:
                        fridge_display_label[uid] = lbl



                def _dbg_meas(uid: str, tag: str):
                    # SS view
                    ss = (
                        st.session_state.get("update_meta", {})
                        .get("measure", {})
                        .get("fridges", {})
                        .get(uid, {})
                        or {}
                    )
                    ss_url = (ss.get("notion", "") or "").strip()
                    ss_id  = (ss.get("notion_page_id", "") or "").strip()

                    # DB view
                    # runx = firestore_get("runs", loaded_run_no, id_token)
                    runx = firestore_get("runs", loaded_run_doc_id, id_token)
                    metax = firestore_to_python((runx or {}).get("fields", {}).get("metadata", {}))
                    db = (metax.get("measure", {}).get("fridges", {}).get(uid, {}) or {})
                    db_url = (db.get("notion", "") or "").strip()
                    db_id  = (db.get("notion_page_id", "") or "").strip()



                # ------------------------------------------------------------
                # 🔧 PRUNE MEASUREMENT METADATA BASED ON FLOW (AUTHORITATIVE)
                # ------------------------------------------------------------

                # 1) Collect fridge_uids from Measurement flow
                flow_fridge_uids = set()
                for layer in (st.session_state.get("update_layers") or []):
                    if (layer.get("layer_name") or "").strip().lower() != "measurement":
                        continue
                    for sub in (layer.get("substeps") or []):
                        uid = (sub.get("fridge_uid") or "").strip()
                        if uid:
                            flow_fridge_uids.add(uid)

                # 2) Prune metadata.measure.fridges to match flow
                meta_measure = st.session_state.get("update_meta", {}).get("measure", {})
                meta_fridges = meta_measure.get("fridges", {})

                if isinstance(meta_fridges, dict):
                    stale_uids = set(meta_fridges.keys()) - flow_fridge_uids

                    if stale_uids:
                        for uid in stale_uids:
                            meta_fridges.pop(uid, None)

                        # Write pruned metadata back to Firestore
                        firestore_update_field(
                            "runs",
                            # loaded_run_no,
                            loaded_run_doc_id,
                            "metadata.measure.fridges",
                            meta_fridges,
                            id_token=id_token,
                        )

                # ------------------------------------------------------------
                # 🔒 Preserve Measurement Notion facts (write-once like FABIN)
                # AND prevent firestore_set from wiping nested fridge fields:
                # - merge DB fridge dict → then overlay SS dict
                # - notion/notion_page_id are write-once: never overwritten by ""
                # ------------------------------------------------------------
                try:
                    # run0  = firestore_get("runs", loaded_run_no, id_token)
                    run0  = firestore_get("runs", loaded_run_doc_id, id_token)
                    meta0 = firestore_to_python((run0 or {}).get("fields", {}).get("metadata", {}))
                    db_fridges = (meta0.get("measure", {}).get("fridges", {}) or {})

                    fr_ss = (
                        st.session_state.setdefault("update_meta", {})
                        .setdefault("measure", {})
                        .setdefault("fridges", {})
                    )

                    merged = {}

                    # 1) start from DB as baseline (full dict)
                    for uid, dbm in (db_fridges or {}).items():
                        if not isinstance(dbm, dict):
                            continue

                        ssm = fr_ss.get(uid, {})
                        if not isinstance(ssm, dict):
                            ssm = {}

                        out = dict(dbm)          # baseline = DB
                        out.update(ssm)          # overlay SS edits

                        # write-once notion fields: never allow empty SS to wipe DB
                        db_url = (dbm.get("notion", "") or "").strip()
                        db_id  = (dbm.get("notion_page_id", "") or "").strip()

                        ss_url = (ssm.get("notion", "") or "").strip()
                        ss_id  = (ssm.get("notion_page_id", "") or "").strip()

                        if (not ss_url) and db_url:
                            out["notion"] = db_url
                        if (not ss_id) and db_id:
                            out["notion_page_id"] = db_id

                        # 🔧 WRITE-ONCE INVARIANT REPAIR (critical)
                        # If page_id exists but notion URL is missing, reconstruct deterministically.
                        if out.get("notion_page_id") and not (out.get("notion") or "").strip():
                            out["notion"] = "https://www.notion.so/" + out["notion_page_id"].replace("-", "")

                        merged[uid] = out

                    # 2) include any SS-only fridges not yet in DB (should be rare, but safe)
                    for uid, ssm in fr_ss.items():
                        if uid in merged:
                            continue
                        if not isinstance(ssm, dict):
                            continue
                        merged[uid] = dict(ssm)

                    # 3) write merged back into session (this is what firestore_set will persist)
                    st.session_state["update_meta"]["measure"]["fridges"] = merged

                except Exception as e:
                    st.warning(f"Measurement Notion preserve/merge failed (non-blocking): {e}")

                firestore_set(
                    "runs",
                    loaded_run_doc_id,
                    {
                        "run_no": loaded_run_no,
                        "class": st.session_state["loaded_run_class"],  # ✅ REQUIRED
                        "device_name": fields["device_name"]["stringValue"],
                        "created_date": fields["created_date"]["stringValue"],
                        "creator": fields["creator"]["stringValue"],
                        "steps": st.session_state["update_layers"],
                        "metadata": st.session_state["update_meta"],
                    },
                    id_token=id_token,
                )


                flow_fridge_labels = {}

                for layer in (st.session_state.get("update_layers") or []):
                    if (layer.get("layer_name") or "").strip().lower() != "measurement":
                        continue
                    for sub in (layer.get("substeps") or []):
                        uid = (sub.get("fridge_uid") or "").strip()
                        label = (sub.get("label") or "").strip()
                        if uid and label:
                            flow_fridge_labels[uid] = label

                meta_measure = st.session_state.get("update_meta", {}).get("measure", {})
                meta_fridges = meta_measure.get("fridges", {})

                changed = False
                for uid, meta in meta_fridges.items():
                    flow_label = flow_fridge_labels.get(uid)
                    if flow_label and meta.get("label") != flow_label:
                        meta["label"] = flow_label
                        changed = True

                if changed:
                    for uid, meta in meta_fridges.items():
                        flow_label = flow_fridge_labels.get(uid)
                        if flow_label and meta.get("label") != flow_label:
                            # keep local cache consistent
                            meta["label"] = flow_label

                            # ✅ update ONLY the label field (do NOT overwrite entire fridges map)
                            firestore_update_field(
                                "runs",
                                # loaded_run_no,
                                loaded_run_doc_id,
                                f"metadata.measure.fridges.{uid}.label",
                                flow_label,
                                id_token=id_token,
                            )


                # ------------------------------------------------------------
                # 🔧 PRUNE PACKAGE METADATA BASED ON FLOW (AUTHORITATIVE)
                # ------------------------------------------------------------

                # 1) Collect chip_uids from Package flow
                flow_chip_uids = set()
                for layer in (st.session_state.get("update_layers") or []):
                    if (layer.get("layer_name") or "").strip().lower() != "package":
                        continue
                    for sub in (layer.get("substeps") or []):
                        uid = (sub.get("chip_uid") or "").strip()
                        if uid:
                            flow_chip_uids.add(uid)

                # 2) Prune metadata.package.chips to match flow
                meta_package = st.session_state.get("update_meta", {}).get("package", {})
                meta_chips = meta_package.get("chips", {})

                if isinstance(meta_chips, dict):
                    stale_uids = set(meta_chips.keys()) - flow_chip_uids

                    if stale_uids:
                        for uid in stale_uids:
                            meta_chips.pop(uid, None)

                        # Write pruned metadata back to Firestore
                        firestore_update_field(
                            "runs",
                            # loaded_run_no,
                            loaded_run_doc_id,
                            "metadata.package.chips",
                            meta_chips,
                            id_token=id_token,
                        )



                # ====================================================
                # ✅ MEASUREMENT NOTION: trigger ONLY on cooldown_start edge
                #    - create when cooldown_start: "" -> non-empty
                #    - clear+archive when cooldown_start: non-empty -> ""
                #    - notion/notion_page_id are write-once facts, only reset on cooldown_start clear
                # ====================================================
                if sync_measure_notion:

                    try:
                    
                        ###################### new
                        # ------------------------------------------------------------
                        # 🔒 Measurement baseline snapshot
                        # NOTE:
                        # - Measurement timestamps (cooldown_start) are written eagerly
                        # - Firestore is therefore NOT a valid "previous" state
                        # - Baseline must come from run-load snapshot only
                        # ------------------------------------------------------------
                        st.session_state.setdefault("prev_measure_fridges_snapshot", {})


                        # 0) previous snapshot from run-load (Step A)
                        prev_fridges = st.session_state.get("prev_measure_fridges_snapshot", {}) or {}

                        # 1) read back Firestore after write (authoritative post-save state)
                        # run_data_live = firestore_get("runs", loaded_run_no, id_token)
                        run_data_live = firestore_get("runs", loaded_run_doc_id, id_token)
                        fields_live = (run_data_live or {}).get("fields", {})
                        meta_live = firestore_to_python(fields_live.get("metadata", {})) if fields_live else {}
                        meas_live = (meta_live or {}).get("measure", {}) if isinstance(meta_live, dict) else {}
                        fridges_live = (meas_live or {}).get("fridges", {}) if isinstance(meas_live, dict) else {}

                        # 2) build a uid -> label map from the *saved* steps (or update_layers)
                        fridge_label = {}
                        for layer in (st.session_state.get("update_layers") or []):
                            if (layer.get("layer_name") or "").strip().lower() != "measurement":
                                continue
                            for sub in layer.get("substeps", []) or []:
                                uid = sub.get("fridge_uid")
                                if not uid:
                                    continue
                                fridge_label[uid] = sub.get("label", sub.get("name", "Measurement"))



                        # 3) edge-detect per fridge_uid
                        for fridge_uid, cur_meta in (fridges_live or {}).items():
                            if not isinstance(cur_meta, dict):
                                continue

                            #### old
                            # prev_meta = prev_fridges.get(fridge_uid, {}) if isinstance(prev_fridges, dict) else {}                            
                            # prev_start = (prev_meta.get("cooldown_start", "") or "").strip()
                            
                            #### new
                            # ------------------------------------------------------------
                            # 🔒 Immutable run-load snapshot (Measurement only)
                            # DO NOT mutate this inside save logic
                            # ------------------------------------------------------------
                            prev_meta = (
                                st.session_state
                                .get("prev_measure_fridges_snapshot", {})
                                .get(fridge_uid, {})
                                or {}
                            )

                            prev_start = (prev_meta.get("cooldown_start", "") or "").strip()
                            cur_start  = (cur_meta.get("cooldown_start", "") or "").strip()

                            prev_warm = (prev_meta.get("warmup_start", "") or "").strip()
                            cur_warm  = (cur_meta.get("warmup_start", "") or "").strip()

                            prev_notion_url = (prev_meta.get("notion", "") or "").strip()
                            cur_notion_url  = (cur_meta.get("notion", "") or "").strip()

                            prev_page_id = (prev_meta.get("notion_page_id", "") or "").strip()
                            cur_page_id  = (cur_meta.get("notion_page_id", "") or "").strip()

                            created_this_save = False   # ✅ ADD THIS LINE HERE
                            # page_exists = bool(prev_page_id or cur_page_id)
                            page_exists = bool(cur_page_id)

                            # ------------------------------------------------------------
                            # 🔒 Consistency repair: page_id is authoritative
                            # If page_id is empty but URL exists → clear URL
                            # ------------------------------------------------------------
                            if (not cur_page_id) and cur_notion_url:
                                firestore_update_field(
                                    "runs",
                                    loaded_run_doc_id,
                                    f"metadata.measure.fridges.{fridge_uid}.notion",
                                    "",
                                    id_token=id_token,
                                )

                                st.session_state["update_meta"]["measure"]["fridges"][fridge_uid]["notion"] = ""
                                cur_meta["notion"] = ""


                            # # 🔍 DEBUG 1 — show edge inputs
                            # st.warning(
                            #     f"[DBG1] uid={uid} "
                            #     f"prev_start='{prev_start}' "
                            #     f"cur_start='{cur_start}' "
                            #     f"page_id='{cur_page_id}'"
                            # )

                            # ---------------------------
                            # CREATE: "" -> non-empty
                            # ---------------------------
                            if (not prev_start) and cur_start:
                                # Firestore is the guard: only create if notion/page_id are currently empty
                                # if (not cur_notion_url) and (not cur_page_id):
                                st.warning(f"[DBG2] ARCHIVE BLOCK ENTERED uid={uid}")

                                if not cur_page_id:
                                    label = fridge_label.get(fridge_uid, "Measurement")
                                    db_url = _pick_meas_db_url(label)
                                    name_yymmdd = (cur_start or "").strip().replace("-", "")[2:8]  # "2026-01-23 ..." -> "260123"
                                    utc_iso = cur_start.split(" ")[0]   # "2026-01-23 16:18:41" → "2026-01-23"
                                    # utc_iso = fb_local_str_to_notion_utc_iso(cur_start)

                                    # Name formatting differs by DB
                                    lab = (label or "").strip().lower()
                                    if "blue" in lab:
                                        notion_name = f"BF{name_yymmdd}"
                                    else:
                                        notion_name = f"IO[{name_yymmdd}]"

                                    result = create_measure_page(
                                        notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                        db_url=db_url,
                                        properties={
                                            "Name": notion_name,
                                            "Status": ["In progress"],
                                            "Cooldown dates": utc_iso,
                                        },
                                    )

                                    st.success(f"Measurment Notion page created ({fridge_display_label.get(fridge_uid, label)})")

                                    notion_url = (result.get("url") or "").strip()          # ✅ return key
                                    page_id    = (result.get("page_id") or "").strip()
                                    created_this_save = True   # ✅ ADD THIS LINE HERE

                                    ############# new
                                    # ------------------------------------------------------------
                                    # 🔗 MEASUREMENT ↔ DEVICE RELATION (Main vs Test)
                                    # ------------------------------------------------------------

                                    # 1) Get Fab Notion page_id from metadata (already exists)
                                    fab_notion_url = _get_meta_val(
                                        st.session_state.get("update_meta", {}).get("fab", []),
                                        "Notion",
                                    )
                                    fab_page_id = get_id(fab_notion_url) if fab_notion_url else ""

                                    # 2) Decide relation type from run class
                                    run_class = (st.session_state.get("loaded_run_class") or "").strip().lower()

                                    # default = main device
                                    rel_key = "test_device" if run_class == "test" else "main_device"

                                    if fab_page_id and page_id:
                                        try:
                                            # choose correct Notion property name for this fridge DB
                                            prop_name = _pick_meas_relation_prop(
                                                fridge_label=label,
                                                rel_key=rel_key,
                                            )

                                            set_relation(
                                                notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                                page_id=page_id,              # Measurement page
                                                prop_name=prop_name,          # Exact DB-specific property
                                                related_page_ids=fab_page_id # Fab page
                                            )

                                            st.success(
                                                f"Measurement Notion relation updated "
                                                f"({rel_key.replace('_', ' ').title()} → "
                                                f"{fridge_display_label.get(fridge_uid, label)})"
                                            )

                                        except Exception as e:
                                            st.warning(f"Saved, but relation link failed (non-blocking): {e}")




                                    # ✅ Backfill URL if page_id exists but URL missing (write-once repair)
                                    if page_id and (not cur_notion_url) and notion_url:
                                        firestore_update_field(
                                            "runs",
                                            # loaded_run_no,
                                            loaded_run_doc_id,
                                            f"metadata.measure.fridges.{fridge_uid}.notion",
                                            notion_url,
                                            id_token=id_token,
                                        )
                                        st.session_state["update_meta"]["measure"]["fridges"][fridge_uid]["notion"] = notion_url
                                        cur_meta["notion"] = notion_url

                                    # ✅ Backfill page_id if URL exists but page_id missing (optional)
                                    if notion_url and (not cur_page_id) and page_id:
                                        firestore_update_field(
                                            "runs",
                                            # loaded_run_no,
                                            loaded_run_doc_id,
                                            f"metadata.measure.fridges.{fridge_uid}.notion_page_id",
                                            page_id,
                                            id_token=id_token,
                                        )
                                        st.session_state["update_meta"]["measure"]["fridges"][fridge_uid]["notion_page_id"] = page_id
                                        cur_meta["notion_page_id"] = page_id


                                    # write-once facts: persist to Firestore
                                    if notion_url:
                                        firestore_update_field(
                                            "runs",
                                            loaded_run_doc_id,
                                            f"metadata.measure.fridges.{fridge_uid}.notion",
                                            notion_url,
                                            id_token=id_token,
                                        )


                                    if page_id:
                                        firestore_update_field(
                                            "runs",
                                            # loaded_run_no,
                                            loaded_run_doc_id,
                                            f"metadata.measure.fridges.{fridge_uid}.notion_page_id",
                                            page_id,
                                            id_token=id_token,
                                        )


                                    # keep local session in sync so next saves don’t retrigger
                                    st.session_state.setdefault("update_meta", {}).setdefault("measure", {}).setdefault("fridges", {}).setdefault(fridge_uid, {})
                                    st.session_state["update_meta"]["measure"]["fridges"][fridge_uid]["notion"] = notion_url
                                    st.session_state["update_meta"]["measure"]["fridges"][fridge_uid]["notion_page_id"] = page_id


                            # ---------------------------
                            # RENAME: cooldown_start override (non-empty -> different non-empty)
                            # ---------------------------
                            if prev_start and cur_start and prev_start != cur_start and cur_page_id:

                                name_yymmdd = cur_start.replace("-", "")[2:8]

                                label = fridge_label.get(fridge_uid, "")
                                lab = (label or "").lower()

                                if "blue" in lab:
                                    new_name = f"BF{name_yymmdd}"
                                else:
                                    new_name = f"IO[{name_yymmdd}]"

                                db_url = _pick_meas_db_url(label)   # 🔑 REQUIRED FOR BLUEFORS

                                # Use page_url (required for Bluefors updates in your setup)
                                cur_url = (cur_notion_url or "").strip()

                                # write-once repair fallback: reconstruct URL if missing but page_id exists
                                if (not cur_url) and cur_page_id:
                                    cur_url = f"https://www.notion.so/{cur_page_id.replace('-', '')}"


                                if cur_url:
                                    try:
                                        update_page_properties(
                                            notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                            db_url=db_url,
                                            page_url=cur_url,              # 🔑 page_url (not page_id)
                                            properties={
                                                "Name": new_name,          # plain string (wrapper handles coercion)
                                            },
                                        )

                                        # 2) ALSO update cooldown date-range (date-only)
                                        start_date = cur_start.split(" ")[0]   # YYYY-MM-DD

                                        cur_warm = (cur_meta.get("warmup_start") or "").strip()
                                        end_date = cur_warm.split(" ")[0] if cur_warm else ""

                                        update_date_range(
                                            notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                            page_id=cur_page_id,            # page_id is safest for date ops
                                            prop_name="Cooldown dates",
                                            start_date=start_date,
                                            end_date=end_date,
                                        )

                                        # st.warning(f"[DBG][RENAME] calling update_page_properties for uid={fridge_uid}")
                                        notion_success("Measurement Notion Name & cooldown dates updated", fridge_display_label.get(fridge_uid, label))

                                    except Exception as e:
                                        st.warning(f"[RENAME] Notion rename failed (non-blocking): {e}")
                                else:
                                    st.warning(f"[RENAME] skipped: missing notion url (uid={fridge_uid})")


                            # ---------------------------
                            # RESET+ARCHIVE: non-empty -> ""
                            # ---------------------------
                            if (not cur_start) and page_exists and (not created_this_save):


                                # ------------------------------------------------------------
                                # 0) ARCHIVE the Notion page (if it exists) BEFORE clearing refs
                                # ------------------------------------------------------------
                                page_id_to_archive = (
                                    (cur_meta.get("notion_page_id") or "").strip()
                                    or (prev_meta.get("notion_page_id") or "").strip()
                                )

                                if page_id_to_archive:
                                    try:
                                       
                                        archive_page(
                                            notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                            page_id=page_id_to_archive,
                                            archived=True,
                                            clear_relations=True,
                                        )

                                        notion_success("Related Notion pages deleted)", fridge_display_label.get(fridge_uid, label))

                                    except Exception as e:
                                        st.warning(f"Notion archive failed (non-blocking): {e}")

                                # ------------------------------------------------------------
                                # 1) Clear Firestore pointers (authoritative)
                                # ------------------------------------------------------------
                                firestore_update_field(
                                    "runs",
                                    # loaded_run_no,
                                    loaded_run_doc_id,
                                    f"metadata.measure.fridges.{fridge_uid}.notion",
                                    "",
                                    id_token=id_token,
                                )
                                firestore_update_field(
                                    "runs",
                                    # loaded_run_no,
                                    loaded_run_doc_id,
                                    f"metadata.measure.fridges.{fridge_uid}.notion_page_id",
                                    "",
                                    id_token=id_token,
                                )

                                # ------------------------------------------------------------
                                # 2) Keep local session in sync
                                # ------------------------------------------------------------
                                st.session_state.setdefault("update_meta", {}) \
                                    .setdefault("measure", {}) \
                                    .setdefault("fridges", {}) \
                                    .setdefault(fridge_uid, {})

                                st.session_state["update_meta"]["measure"]["fridges"][fridge_uid]["notion"] = ""
                                st.session_state["update_meta"]["measure"]["fridges"][fridge_uid]["notion_page_id"] = ""


                            # ------------------------------------------------------------
                            # 🧊 Cooldown date-range sync (end = warmup_start)
                            # Rules:
                            # - Only if cooldown_start is non-empty
                            # - End exists iff warmup_start is non-empty
                            # - Update when warmup_start changed OR when page_id just appeared (page created this save)
                            # - If warmup_start cleared, revert Notion to start-only
                            # ------------------------------------------------------------
                            try:
                                if cur_start:
                                    # page_id may be backfilled during CREATE in the same save,
                                    # so re-read from session_state as the most up-to-date source.
                                    ss_meta = (
                                        st.session_state.get("update_meta", {})
                                        .get("measure", {})
                                        .get("fridges", {})
                                        .get(fridge_uid, {})
                                        or {}
                                    )
                                    page_id_live = (ss_meta.get("notion_page_id") or "").strip()

                                    # Detect "page_id became available this save" (create event)
                                    page_id_was_empty = not ((prev_page_id or "").strip())
                                    page_id_now_set   = bool(page_id_live)

                                    # Detect warmup_start changes (covers status changes + overrides)
                                    warm_changed = (prev_warm or "") != (cur_warm or "")

                                    if page_id_now_set and (warm_changed or page_id_was_empty):
                                        start_date = cur_start.split(" ")[0]           # YYYY-MM-DD
                                        end_date   = cur_warm.split(" ")[0] if cur_warm else ""  # "" clears end


                                        # st.warning(f"[DBG][DATE-RANGE] calling update_date_range for uid={fridge_uid}")

                                        update_date_range(
                                            notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                            page_id=page_id_live,
                                            prop_name="Cooldown dates",
                                            start_date=start_date,
                                            end_date=end_date,
                                        )

                                        notion_success("Measurement Notion cooldown date updated", fridge_display_label.get(fridge_uid, label))

                            except Exception as e:
                                st.warning(f"Saved, but Cooldown date-range update failed (non-blocking): {e}")

                        # ------------------------------------------------------------
                        # Measurement → Bluefors Notion: sync "Chip" (multi-select)
                        #
                        # Rule:
                        # - Bluefors only (based on fridge_label[uid])
                        # - If fridge has a Notion page, write Notion property "Chip" = ["C01"] etc.
                        # - chip_uid -> chip label uses Package flow mapping (chip_uid_to_label)
                        # - Skip Notion call if unchanged from last write (no retrieve; too slow)
                        # ------------------------------------------------------------

                        # Build chip_uid -> label map from Package flow (C01, C02, ...)
                        chip_uid_to_label = {}
                        for layer in (st.session_state.get("update_layers") or []):
                            if (layer.get("layer_name") or "").strip().lower() != "package":
                                continue
                            for sub in (layer.get("substeps") or []):
                                cuid = (sub.get("chip_uid") or "").strip()
                                if not cuid:
                                    continue
                                lab = (sub.get("label") or sub.get("name") or "").strip()
                                if lab:
                                    chip_uid_to_label[cuid] = lab

                        # DEBUG: show mapping once (optional)
                        # st.write("[DBG] chip_uid_to_label:", chip_uid_to_label)

                        for bf_uid, bf_meta in (fridges_live or {}).items():
                            if not isinstance(bf_meta, dict):
                                continue

                            # ------------------------------------------------------------
                            # 🔒 Immutable pre-save snapshot (do NOT mutate this)
                            # ------------------------------------------------------------
                            pre_save_fridges = (
                                st.session_state.get("prev_measure_fridges_snapshot", {}) or {}
                            )

                            prev_meta = pre_save_fridges.get(bf_uid, {}) or {}
                            prev_start = (prev_meta.get("cooldown_start") or "").strip()
                           
                            cur_start  = (bf_meta.get("cooldown_start") or "").strip()

                            if not prev_start:
                                continue

                            if prev_start and not cur_start:
                                continue

                            if not cur_start:
                                continue

                            # Bluefors only (use the uid->label map from Measurement flow)
                            bf_label = (fridge_label.get(bf_uid, "") or "").strip().lower()
                            if "blue" not in bf_label:
                                continue

                            bf_notion_url = (bf_meta.get("notion") or "").strip()
                            bf_chip_uid   = (bf_meta.get("chip_uid") or "").strip()

                            if not bf_notion_url:
                                st.warning(f"[DBG][BLUEFORS] skip: no notion url for uid={bf_uid}")
                                continue

                            bf_chip_label = (chip_uid_to_label.get(bf_chip_uid) or "").strip()
                            chip_list = [bf_chip_label] if bf_chip_label else []

                            # Skip if unchanged
                            prev_key = f"prev_bluefors_chip_sig_{loaded_run_doc_id}_{bf_uid}"
                            sig_new = ",".join(chip_list)
                            sig_old = st.session_state.get(prev_key, "")

                            if sig_new == sig_old:
                                st.info("Bluefors skip: unchanged")
                                continue

                            # If chip_uid exists but mapping missing, warn (don’t silently write empty)
                            if bf_chip_uid and (not bf_chip_label):
                                st.warning(
                                    f"[DBG][BLUEFORS] chip_uid '{bf_chip_uid}' not found in Package flow mapping; "
                                    f"cannot update Notion 'Chip'."
                                )
                                continue

                            # Use the same working rule as CREATE: label -> db_url
                            db_url_used = _pick_meas_db_url(fridge_label.get(bf_uid, "Measurement"))

                            if not db_url_used:
                                st.warning(f"[DBG][BLUEFORS] db_url empty for uid={bf_uid} label='{fridge_label.get(bf_uid)}'")
                                continue

                            try:
                                # st.write("[DBG][BLUEFORS] calling notion_update_page.py ...")
                                # st.warning(f"[DBG][BLUEFORS-CHIP] calling update_page_properties for uid={bf_uid}")

                                update_page_properties(
                                    notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                    page_url=bf_notion_url,
                                    db_url=db_url_used,
                                    properties={
                                        "Chip": chip_list,
                                    },
                                )

                                st.session_state[prev_key] = sig_new
                                # st.write("[DBG][BLUEFORS] notion update OK")
                                notion_success("Bluefors Notion chip list updated", fridge_display_label.get(bf_uid, fridge_label.get(bf_uid)))

                            except Exception as e:
                                st.warning(
                                    f"Saved, but Bluefors Chip -> Notion sync failed "
                                    f"(uid={bf_uid}, non-blocking): {e}"
                                )

                            st.session_state["prev_measure_fridges_snapshot"] = {
                                uid: dict(meta) for uid, meta in fridges_live.items()
                            }



                        # 4) refresh snapshot AFTER processing so next save edge-detect is correct
                        st.session_state["prev_measure_fridges_snapshot"] = {
                            uid: dict(meta) for uid, meta in (fridges_live or {}).items()
                            if isinstance(meta, dict)
                        }

                        # notion_success("Measurement Notion sync completed")

                    except Exception as e:
                        st.warning(f"Measurement Notion sync failed (non-blocking): {e}")



                # 2) Optional: sync Design Lotid → Fab Notion page "Lot ID"
                if sync_fab_notion_lotid:
                    new_lotid = _get_meta_val(
                        st.session_state["update_meta"].get("design", []),
                        "Lotid",
                    )

                    new_chip_size = _get_meta_val(
                        st.session_state["update_meta"].get("design", []),
                        "Chip size (mm2)",
                    )


                    fab_notion_url = _get_meta_val(
                        st.session_state["update_meta"].get("fab", []),
                        "Notion",
                    )


                    prev_key = f"prev_design_lotid_chip_{loaded_run_doc_id}"
                    old_sig = st.session_state.get(prev_key, ("", ""))

                    sig_new = (new_lotid or "", new_chip_size or "")

                    # update if either Lotid OR Chip size changed
                    if fab_notion_url and (sig_new != old_sig) and (sig_new[0] or sig_new[1]):
                        props = {}
                        if new_lotid:
                            props["Lot ID"] = new_lotid
                        if new_chip_size:
                            props["Chip size (mm2)"] = new_chip_size

                        if props:
                            try:
                                update_page_properties(
                                    notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                    # db_url=st.secrets["notion"]["NOTION_FAB_DB_URL"],
                                    db_url=_pick_fab_db_url(st.session_state["loaded_run_class"]),
                                    page_url=fab_notion_url,
                                    properties=props,
                                )
                                
                                notion_success("Fab Notion updated")

                            except Exception as e:
                                st.warning(f"Saved, but Notion update failed: {e}")

                    st.session_state[prev_key] = sig_new


                    # st.session_state[prev_key] = new_lotid


                # 3) Always sync Fab detail fields → Fab Notion page

                if sync_fab_notion_fields:
                    fab_notion_url = _get_meta_val(
                        st.session_state["update_meta"].get("fab", []),
                        "Notion",
                    )

                    fab_props = _build_fab_notion_props(st.session_state["update_meta"])
                    prev_key2 = f"prev_fab_notion_props_sig_{loaded_run_doc_id}"
                    sig_new = str(sorted(fab_props.items()))
                    sig_old = st.session_state.get(prev_key2, "")

                    if fab_notion_url and fab_props and (sig_new != sig_old):
                        try:
                       
                            update_page_properties(
                                notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                # db_url=st.secrets["notion"]["NOTION_FAB_DB_URL"],
                                db_url=_pick_fab_db_url(st.session_state["loaded_run_class"]),
                                page_url=fab_notion_url,
                                properties=fab_props,
                            )

                            notion_success("Fab Notion sync completed")

                        except Exception as e:
                            st.warning(f"Saved, but Fab Notion fields update failed: {e}")

                        st.session_state[prev_key2] = sig_new


                if sync_pkg_bond_to_fab_notion:
                    # ------------------------------------------------------------
                    # 3b) Sync Package bonded chips -> Fab Notion "Bond" (multi-select)
                    #
                    # Rule:
                    # - compute bonded labels = { C01, C02, ... } where bond_date is non-empty
                    # - write Notion property "Bond" = sorted(list(bonded_labels))
                    # - skip Notion call if the computed set is identical to what we last wrote
                    # - no Notion retrieve (too slow)
                    # ------------------------------------------------------------
                    try:

                        fab_notion_url = _get_meta_val(
                            (st.session_state.get("update_meta", {}) or {}).get("fab", []),
                            "Notion",
                        )

                        # 1) Build chip_uid -> label mapping from Package flow
                        chip_uid_to_label = {}
                        for layer in (st.session_state.get("update_layers") or []):
                            if (layer.get("layer_name") or "").strip().lower() != "package":
                                continue
                            for sub in (layer.get("substeps") or []):
                                chip_uid = sub.get("chip_uid") or ""
                                if not chip_uid:
                                    continue
                                lab = sub.get("label") or sub.get("name") or ""
                                chip_uid_to_label[chip_uid] = (lab or "").strip()

                        # st.write("DBG chip_uid_to_label:", chip_uid_to_label)

                        # 2) Compute bonded labels from chip-centric package metadata
                        pkg_chips = (
                            (st.session_state.get("update_meta", {}) or {})
                            .get("package", {})
                            .get("chips", {})
                            or {}
                        )

                        # st.write("DBG pkg_chips:", pkg_chips)

                        bonded = set()
                        for chip_uid, chipm in (pkg_chips or {}).items():
                            if not isinstance(chipm, dict):
                                continue
                            bd = (chipm.get("bond_date") or "").strip()
                            if bd:
                                lab = (chip_uid_to_label.get(chip_uid) or "").strip()
                                if lab:
                                    bonded.add(lab)

                        bonded_list = sorted(bonded)
                        # 2b) Total chip count comes from Fab metadata "# of chips"
                        fab_meta = (st.session_state.get("update_meta", {}) or {}).get("fab", []) or []

                        # Primary key in your Firebase is "Qty chips"
                        nchips_raw = _get_meta_val(fab_meta, "Qty chips")

                        # Backward/alternate key support (if you ever used it elsewhere)
                        if nchips_raw is None or str(nchips_raw).strip() == "":
                            nchips_raw = _get_meta_val(fab_meta, "# of chips")


                        nchips = 0
                        try:
                            if nchips_raw is not None and str(nchips_raw).strip() != "":
                                nchips = int(float(str(nchips_raw).strip()))
                        except Exception:
                            nchips = 0

                        stock_list = None
                        if nchips <= 0:
                            st.warning('Cannot sync "Stock" to Notion: please set Fab metadata "Qty chips" first.')
                        else:
                            all_labels = {f"C{i:02d}" for i in range(1, nchips + 1)}
                            stock_set = all_labels - set(bonded_list)
                            stock_list = sorted(stock_set)


                        # 3) Skip Notion call if unchanged from last write
                        prev_key3 = f"prev_fab_bond_sig_{loaded_run_doc_id}"

                        if stock_list is None:
                            sig_new3 = "B=" + ",".join(bonded_list)
                        else:
                            sig_new3 = "B=" + ",".join(bonded_list) + "|S=" + ",".join(stock_list)

                        sig_old3 = st.session_state.get(prev_key3, "")

                        if not fab_notion_url:
                            st.warning("Fab Notion URL missing; cannot sync Bond/Stock.")

                        props = {"Bond": bonded_list}  # multi-select always safe
                        if stock_list is not None:
                            props["Stock"] = stock_list

                        if fab_notion_url and (sig_new3 != sig_old3):

                            update_page_properties(
                                notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                # db_url=st.secrets["notion"]["NOTION_FAB_DB_URL"],
                                db_url=_pick_fab_db_url(st.session_state["loaded_run_class"]),
                                page_url=fab_notion_url,
                                properties=props,
                            )

                            st.session_state[prev_key3] = sig_new3

                            notion_success("Fab Notion sync completed")

                    except Exception as e:
                        st.warning(f"Saved, but Bond -> Notion sync failed (non-blocking): {e}")


                # ------------------------------------------
                # 🔒 Reset all status locks after save
                # ------------------------------------------
                st.session_state["_reset_locks"] = True
                st.rerun()



            def apply_editor_changes_before_save():

                pass


            def save_all_changes(apply_editor=True):
                if apply_editor:
                    apply_editor_changes_before_save()

                # ------------------------------------------------
                # 🔒 FINALIZE DESIGN (flat metadata)
                # ------------------------------------------------
                if "design" in st.session_state["update_meta"]:
                    st.session_state["update_meta"]["design"] = normalize_meta(
                        st.session_state["update_meta"]["design"]
                    )

                # ------------------------------------------------
                # 🔒 FINALIZE FAB (flat metadata)
                # ------------------------------------------------
                if "fab" in st.session_state["update_meta"]:
                    st.session_state["update_meta"]["fab"] = normalize_meta(
                        st.session_state["update_meta"]["fab"]
                    )


                # ✅ Option A: Lotid must be DESIGN-only → remove from FAB metadata to prevent drift
                fab_list = st.session_state["update_meta"].get("fab", [])
                if isinstance(fab_list, list):
                    st.session_state["update_meta"]["fab"] = [
                        it for it in fab_list
                        if (it.get("key") or "").strip().lower() not in ("lotid", "lot id", "lotid ")
                    ]


                # ------------------------------------------------
                # 🔒 FINAL SOURCE OF TRUTH — PACKAGE IS CHIP-CENTRIC
                # ------------------------------------------------
                package_meta = st.session_state["update_meta"].get("package", {})
                old_chips = (
                    package_meta.get("chips", {})
                    if isinstance(package_meta, dict)
                    else {}
                )

                st.session_state["update_meta"]["package"] = {
                    "chips": build_package_chip_meta(
                        st.session_state["update_layers"],
                        old_chips
                    )
                }


                # ------------------------------------------------
                # ✅ LAST: write everything once to Firestore
                # ------------------------------------------------
                save_full_run()
                st.rerun()

            # ------------------------------------------------------------
            # Status editor
            # ------------------------------------------------------------

            # stage = st.tabs(["Design", "Fabrication", "Package", "Measurement", "Notion Conents"])
            stage = st.tabs(["Design", "Fabrication", "Package", "Measurement"])


            for stage_name, stage_tab in zip(
                # ["Design", "Fabrication", "Package", "Measurement", "Notion Conents"],
                ["Design", "Fabrication", "Package", "Measurement"],

                stage
            ):
                with stage_tab:

                    # map UI tab -> your internal layer/meta names
                    if stage_name == "Design":
                        target_layer = "design"
                        target_meta  = "design"
                    elif stage_name == "Fabrication":
                        target_layer = "fabrication"
                        target_meta  = "fab"
                    elif stage_name == "Package":
                        target_layer = "package"
                        target_meta  = "package"
                    else:  # Measurement
                        target_layer = "measurement"
                        target_meta  = "measure"

                    stage_key = f"upd_{target_layer}_{loaded_run_doc_id}"

                    # (optional) If you also want the old "Save Fab" behavior here later, we can add it similarly.



                    # now create the sub-tabs
                    sub_flow, sub_status, sub_details, sub_notion = st.tabs(["Flow", "Status", "Details", "Notion"])

                    with sub_flow:
                        update_flow_editor(
                            st.session_state["update_layers"],
                            layer_filter=target_layer,
                            show_layer_tabs=False,
                            key_prefix=f"{stage_key}_flow",
                        )


                    with sub_status:


                        render_status_editor(
                            layers_py=st.session_state["update_layers"],
                            fields=fields,
                            loaded_run_doc_id=loaded_run_doc_id,
                            id_token=id_token,
                            target_layer=target_layer,
                            key_prefix=f"{stage_key}_status",
                        )


                    with sub_details:
                        # ✅ Option A: Lotid is Design-owned → hide Lotid field in FAB details UI
                        hide_keys = ("Lotid", "Lot ID", "LotID") if target_meta == "fab" else ()

                        render_metadata_ui(
                            loaded_run_no=loaded_run_no,
                            loaded_run_doc_id=loaded_run_doc_id,
                            fields=fields,
                            layers_py=st.session_state["update_layers"],
                            update_layers=st.session_state["update_layers"],
                            update_meta=st.session_state["update_meta"],
                            save_full_run=save_full_run,
                            id_token=id_token,
                            stage_filter=target_meta,
                            key_prefix=f"{target_meta}_",
                            hide_keys=hide_keys,   # ✅ ADD THIS LINE
                        )



                        # ==========================================
                        # ✅ DESIGN ONLY: file upload / replace block
                        # ==========================================
                        st.divider()

                        if target_meta == "design":
                            # --- helper: upsert into design meta_list ---
                            def _upsert_design_kv(key, val):
                                design_list = st.session_state["update_meta"].setdefault("design", [])
                                for it in design_list:
                                    if (it.get("key") or "").strip().lower() == key.lower():
                                        it["value"] = val
                                        return
                                design_list.append({"key": key, "value": val})

                            def _get_design_val(key):
                                for it in st.session_state["update_meta"].get("design", []):
                                    if (it.get("key") or "").strip().lower() == key.lower():
                                        return it.get("value", "")
                                return ""

                            file_url  = _get_design_val("File")
                            file_id   = _get_design_val("FileId")
                            file_name = _get_design_val("FileName")
                            has_file = bool(file_url or file_id or file_name)

                            left, right = st.columns([1, 1])

                            with left:
                                # st.markdown("**Current design file**")
                                st.markdown("Current design file")
                                st.caption(file_name or "None uploaded")

                            with right:
                                label = "Replace design file" if has_file else "Upload design file"

                                uploaded = st.file_uploader(
                                    label,
                                    key=f"upd_design_uploader_{loaded_run_doc_id}_{st.session_state['upd_design_upload_nonce']}",
                                    type=None,
                                )

                                if uploaded is not None:
                                    sig = (uploaded.name, uploaded.size)

                                    if st.session_state.get("upd_design_last_sig") == sig:
                                        st.info("Same file already uploaded (name+size match). Choose a different file to replace.")
                                    else:
                                        btn = "Upload" if not has_file else "Upload & Replace"

                                        if st.button(btn, key=f"upd_design_upload_btn_{loaded_run_doc_id}", use_container_width=True):
                                            try:
                                                # ✅ capture old file id BEFORE uploading (replace case)
                                                old_id = _get_design_val("FileId") if has_file else ""

                                                with st.spinner("Uploading to Drive…"):
                                                    out = upload_file_via_cleanroom_api(
                                                        uploaded_file=uploaded,
                                                        filename=uploaded.name,
                                                        folder_id=st.secrets["app"]["drive_folder_id_design"],
                                                    )

                                                if not out.get("success", False):
                                                    st.error(f"Upload failed: {out}")
                                                else:
                                                    file_url  = out.get("url", "")
                                                    file_id   = out.get("id", "")
                                                    file_name = out.get("name", uploaded.name)

                                                    _upsert_design_kv("File", file_url)        # ✅ Viewer uses this
                                                    _upsert_design_kv("FileId", file_id)
                                                    _upsert_design_kv("FileName", file_name)

                                                    # ✅ Trash old file only after new upload succeeds
                                                    if old_id and old_id != file_id:
                                                        del_out = delete_file_via_cleanroom_api(file_id=old_id)
                                                        if not del_out.get("success", False):
                                                            st.warning(
                                                                "New file uploaded, but old file could not be trashed: "
                                                                + str(del_out.get("error", "unknown error"))
                                                            )

                                                    st.session_state["upd_design_last_sig"] = sig
                                                    st.session_state["upd_design_upload_nonce"] += 1

                                                    st.success("Design file uploaded (old file moved to Trash).")
                                                    st.rerun()

                                            except Exception as e:
                                                st.error(f"Upload error: {e}")


                        # ==========================================
                        # ✅ FAB ONLY: multi-file upload / replace / delete
                        # ==========================================
                        if target_meta == "fab":

                            # ----------------------------
                            # Init per-run fab attachments
                            # ----------------------------
                            if st.session_state.get("_upd_fab_files_for") != loaded_run_doc_id:
                                fab_meta = st.session_state["update_meta"].get("fab", [])

                                files = []
                                for row in fab_meta:
                                    k = row.get("key", "")
                                    if k.startswith("FileId_"):
                                        idx = int(k.split("_")[1])
                                        fid = row.get("value", "")
                                        fname = next(
                                            (r["value"] for r in fab_meta if r.get("key") == f"FileName_{idx}"),
                                            "",
                                        )
                                        files.append({
                                            "id": fid,
                                            "name": fname,
                                            "url": "",
                                            "sig": None,
                                        })

                                st.session_state["update_fab_files"] = files
                                st.session_state["_upd_fab_files_for"] = loaded_run_doc_id
                                st.session_state["upd_fab_upload_nonce"] = 0

                            fab_files = st.session_state.setdefault("update_fab_files", [])


                            def _upsert_fab_kv(key, val):
                                fab_list = st.session_state["update_meta"].setdefault("fab", [])
                                for it in fab_list:
                                    if (it.get("key") or "").strip().lower() == key.lower():
                                        it["value"] = val
                                        return
                                fab_list.append({"key": key, "value": val})

                            def _drop_fab_prefix(prefix: str):
                                fab_list = st.session_state["update_meta"].setdefault("fab", [])
                                pref = prefix.lower()
                                fab_list[:] = [
                                    it for it in fab_list
                                    if not ((it.get("key") or "").strip().lower().startswith(pref))
                                ]

                            def _sync_fab_files_to_meta():
                                # remove old attachment keys
                                _drop_fab_prefix("fileid_")
                                _drop_fab_prefix("filename_")

                                # legacy pointer = latest attachment (keep your existing scheme)
                                if fab_files:
                                    last = fab_files[-1]
                                    _upsert_fab_kv("FileId", last.get("id", ""))
                                    _upsert_fab_kv("FileName", last.get("name", ""))
                                    if last.get("url"):
                                        _upsert_fab_kv("File", last.get("url", ""))
                                else:
                                    _upsert_fab_kv("FileId", "")
                                    _upsert_fab_kv("FileName", "")
                                    _upsert_fab_kv("File", "")

                                # write numbered attachment keys back
                                for i, f in enumerate(fab_files, start=1):
                                    _upsert_fab_kv(f"FileId_{i}", f.get("id", ""))
                                    _upsert_fab_kv(f"FileName_{i}", f.get("name", ""))

 
                            tab_add, tab_edit = st.tabs(["File add", "File edit"])

                            # -------------------------
                            # ➕ Add tab
                            # -------------------------
                            with tab_add:
                                col, _ = st.columns([1,1])
                                with col:
                                    uploaded_add = st.file_uploader(
                                        "Add",
                                        key=f"upd_fab_add_{loaded_run_doc_id}_{st.session_state['upd_fab_upload_nonce']}",
                                        type=None,
                                    )

                                if uploaded_add is not None:
                                    with col:
                                        if st.button("Add attachment", key=f"upd_fab_add_btn_{loaded_run_doc_id}", use_container_width=True):
                                            out = upload_file_via_cleanroom_api(
                                                uploaded_file=uploaded_add,
                                                filename=uploaded_add.name,
                                                folder_id=st.secrets["app"]["drive_folder_id_fab"],
                                            )
                                            if out.get("success"):
                                                fab_files.append({
                                                    "id": out.get("id",""),
                                                    "name": out.get("name", uploaded_add.name),
                                                    "url": out.get("url",""),
                                                    "sig": (uploaded_add.name, uploaded_add.size),
                                                })
                                                _sync_fab_files_to_meta()
                                                st.session_state["upd_fab_upload_nonce"] += 1
                                                st.success("Attachment added.")
                                                st.rerun()
                                            else:
                                                st.error(out.get("error","Upload failed"))

                            # -------------------------
                            # ✏️ Edit tab
                            # -------------------------

                            with tab_edit:
                                if not fab_files:
                                    st.caption("No Fab attachments yet.")
                                else:
                                    # ✅ replace-mode flag (per run)
                                    replace_flag_key = f"fab_replace_mode_{loaded_run_doc_id}"
                                    if replace_flag_key not in st.session_state:
                                        st.session_state[replace_flag_key] = False

                                    sel_c1, _, sel_c3 = st.columns([.4, .3, .3])
                                    with sel_c1:
                                        sel = st.selectbox(
                                            "Select files",
                                            options=list(range(len(fab_files))),
                                            format_func=lambda i: fab_files[i].get("name", f"Attachment {i+1}"),
                                            key=f"upd_fab_edit_sel_{loaded_run_doc_id}",
                                        )

                                    with sel_c3:
                                        st.markdown("")
                                        st.markdown(f"**Selected:** {fab_files[sel].get('name','')}")

                                    # ------------------------------------------------------------
                                    # Step 1: click Replace selected → then show uploader + confirm
                                    # ------------------------------------------------------------
                                    c1, c2 = st.columns([1, 1])

                                    with c1:
                                        # If not in replace mode, show the "Replace selected" button
                                        if not st.session_state[replace_flag_key]:
                                            if st.button(
                                                "Replace selected",
                                                key=f"upd_fab_replace_start_{loaded_run_doc_id}",
                                                use_container_width=True,
                                            ):
                                                st.session_state[replace_flag_key] = True
                                                st.rerun()

                                        # If in replace mode, show uploader + Confirm + Cancel
                                        else:
                                            st.caption("Choose a replacement file")
                                            uploaded_rep = st.file_uploader(
                                                "Replacement file",
                                                key=f"upd_fab_rep_{loaded_run_doc_id}_{sel}_{st.session_state['upd_fab_upload_nonce']}",
                                                type=None,
                                                label_visibility="collapsed",
                                            )

                                            cc1, cc2 = st.columns([1, 1])

                                            with cc1:
                                                if st.button(
                                                    "Confirm replace",
                                                    disabled=(uploaded_rep is None),
                                                    key=f"upd_fab_replace_confirm_{loaded_run_doc_id}",
                                                    use_container_width=True,
                                                ):
                                                    out = upload_file_via_cleanroom_api(
                                                        uploaded_file=uploaded_rep,
                                                        filename=uploaded_rep.name,
                                                        folder_id=st.secrets["app"]["drive_folder_id_fab"],
                                                    )
                                                    if out.get("success"):
                                                        old_id = fab_files[sel].get("id", "")
                                                        new_id = out.get("id", "")

                                                        fab_files[sel] = {
                                                            "id": new_id,
                                                            "name": out.get("name", uploaded_rep.name),
                                                            "url": out.get("url", ""),
                                                            "sig": (uploaded_rep.name, uploaded_rep.size),
                                                        }

                                                        _sync_fab_files_to_meta()

                                                        if old_id and old_id != new_id:
                                                            del_out = delete_file_via_cleanroom_api(file_id=old_id)
                                                            if not del_out.get("success"):
                                                                st.warning("Old file could not be trashed.")

                                                        st.session_state["upd_fab_upload_nonce"] += 1
                                                        st.session_state[replace_flag_key] = False
                                                        st.success("Replaced.")
                                                        st.rerun()
                                                    else:
                                                        st.error(out.get("error", "Replace failed"))

                                            with cc2:
                                                if st.button(
                                                    "Cancel",
                                                    key=f"upd_fab_replace_cancel_{loaded_run_doc_id}",
                                                    use_container_width=True,
                                                ):
                                                    st.session_state[replace_flag_key] = False
                                                    st.rerun()

                                    # -------------------------
                                    # Delete (unchanged)
                                    # -------------------------
                                    with c2:
                                        if st.button(
                                            "Delete selected",
                                            key=f"upd_fab_delete_btn_{loaded_run_doc_id}",
                                            use_container_width=True,
                                        ):
                                            old_id = fab_files[sel].get("id", "")
                                            if old_id:
                                                del_out = delete_file_via_cleanroom_api(file_id=old_id)
                                                if not del_out.get("success"):
                                                    st.warning("Removed from list but not trashed in Drive.")
                                            fab_files.pop(sel)
                                            _sync_fab_files_to_meta()
                                            st.success("Deleted.")
                                            st.rerun()


                    # with sub_notion:
                    #     # Show different Notion UI depending on which stage we are in
                    #     if target_meta == "design":
                    #         # st.info("Design Notion content will be added later.")
                    #         st.write("__Link design page__")
                    #         design_db_url = st.secrets["notion"]["NOTION_DESIGN_DB_URL"]
                    #         st.warning(
                    #             f"Link to an existing Notion page is only available within the following database:\n\n{design_db_url}"
                    #         )

                    #         design_title_input = st.text_input(
                    #             "Page title",
                    #             value=st.session_state.get("loaded_device_name", ""),
                    #             key=f"design_notion_title_{loaded_run_doc_id}",
                    #         )

                    #         if st.button("Link", key=f"btn_design_notion_{loaded_run_doc_id}"):

                    #             meta = st.session_state.get("update_meta", {})
                    #             design_meta = meta.get("design", [])

                    #             # Write-once guard
                    #             existing_url = None
                    #             for it in design_meta:
                    #                 if (it.get("key") or "").strip() == "Notion":
                    #                     existing_url = it.get("value")
                    #                     break

                    #             if existing_url:
                    #                 st.warning("Design Notion URL already exists. Skipping.")
                    #             else:
                    #                 page_url = get_page_url_by_title(
                    #                     notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                    #                     db_url=st.secrets["notion"]["NOTION_DESIGN_DB_URL"],
                    #                     title=design_title_input,
                    #                 )


                    #                 if not page_url:
                    #                     st.warning("No matching page found.")
                    #                 else:
                    #                     design_meta.append({
                    #                         "key": "Notion",
                    #                         "value": page_url,
                    #                     })

                    #                     firestore_update_field(
                    #                         "runs",
                    #                         loaded_run_doc_id,
                    #                         "metadata.design",
                    #                         design_meta,
                    #                         id_token,
                    #                     )

                    #                     st.success("Design Notion URL saved.")
                    #                     # st.rerun()

                    with sub_notion:
                        if target_meta == "design":

                            st.write("__Link design page__")

                            design_db_url = st.secrets["notion"]["NOTION_DESIGN_DB_URL"]

                            st.warning(
                                "Link to an existing Notion page is only available within the following database:\n\n"
                                f"{design_db_url}"
                            )

                            # meta = st.session_state.get("update_meta", {})
                            # design_meta = meta.get("design", [])

                            # # -----------------------------------------
                            # # Check existing Notion URL
                            # # -----------------------------------------
                            # existing_url = None
                            # for it in design_meta:
                            #     if (it.get("key") or "").strip() == "Notion":
                            #         existing_url = it.get("value")
                            #         break

                            meta = st.session_state.get("update_meta", {})
                            design_meta = meta.get("design", []) or []

                            # Robust existing URL detection
                            existing_url = next(
                                (
                                    (it.get("value") or "").strip()
                                    for it in design_meta
                                    if (it.get("key") or "").strip() == "Notion"
                                ),
                                ""
                            )

                            # -----------------------------------------
                            # Title input
                            # -----------------------------------------
                            design_title_input = st.text_input(
                                "Page title",
                                value=st.session_state.get("loaded_device_name", ""),
                                key=f"design_notion_title_{loaded_run_doc_id}",
                            )

                            col_link, col_reset = st.columns([1, 1])

                            # -----------------------------------------
                            # LINK BUTTON
                            # -----------------------------------------
                            with col_link:
                                if st.button("Link", key=f"btn_design_notion_{loaded_run_doc_id}"):

                                    if existing_url.strip():
                                        st.warning("Design Notion URL already exists.")
                                    else:
                                        page_url = get_page_url_by_title(
                                            notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                            db_url=design_db_url,
                                            title=design_title_input,
                                        )

                                        if not page_url:
                                            st.warning("No matching page found.")
                                        else:
                                            design_meta.append({
                                                "key": "Notion",
                                                "value": page_url,
                                            })

                                            # Update session_state first
                                            st.session_state["update_meta"]["design"] = design_meta

                                            firestore_update_field(
                                                "runs",
                                                loaded_run_doc_id,
                                                "metadata.design",
                                                design_meta,
                                                id_token,
                                            )

                                            st.success("Design Notion URL saved.")
                                            st.rerun()

                            # -----------------------------------------
                            # RESET BUTTON (only if link exists)
                            # -----------------------------------------
                            with col_reset:
                                if existing_url:
                                    if st.button("Reset", key=f"btn_reset_design_notion_{loaded_run_doc_id}"):

                                        new_design_meta = [
                                            it for it in design_meta
                                            if (it.get("key") or "").strip() != "Notion"
                                        ]

                                        st.session_state["update_meta"]["design"] = new_design_meta

                                        firestore_update_field(
                                            "runs",
                                            loaded_run_doc_id,
                                            "metadata.design",
                                            new_design_meta,
                                            id_token,
                                        )

                                        st.success("Design Notion link removed.")
                                        # st.rerun()



                        elif target_meta == "fab":
                            st.write(
                                "**Fab page content**"
                            )
                            def _kv_get(meta_list, key: str, default=""):
                                """Case-insensitive get from metadata kv-list: [{'key':..., 'value':...}, ...]."""
                                k = (key or "").strip().lower()
                                for it in (meta_list or []):
                                    if (it.get("key") or "").strip().lower() == k:
                                        return it.get("value", default)
                                return default

                            # -------- Build payload for Fab content subprocess --------
                            meta = st.session_state.get("update_meta", {})
                            design_list = meta.get("design", [])
                            fab_list = meta.get("fab", [])

                            fab_notion_url = (_kv_get(fab_list, "Notion") or "").strip()
                            n_chips = (_kv_get(fab_list, "Qty chips") or "").strip()
                            lotid = (_kv_get(design_list, "Lotid") or "").strip()
                            fabin = (_kv_get(fab_list, "FABIN") or "").strip()
                            fab_type = (_kv_get(fab_list, "Type") or "").strip()

                            # device_name: prefer run-level name if present, else Design metadata Name
                            device_name = (st.session_state.get("loaded_device_name") or "").strip()
                            # if not device_name:
                            #     device_name = (_kv_get(design_list, "Name") or "").strip()

                            # parse num chips safely
                            try:
                                n_chips_int = int(n_chips) if n_chips else 0
                            except Exception:
                                n_chips_int = 0

                            # Validate required inputs
                            missing = []
                            if not fab_notion_url:
                                missing.append("Fab Notion URL")
                            if not lotid:
                                missing.append("Lot ID")
                            if not device_name:
                                # missing.append("Name (run name or Design metadata: Name)")
                                missing.append("Device Name")
                            if not fabin:
                                missing.append("FABIN")
                            if not fab_type:
                                missing.append("Type")
                            if n_chips_int <= 0:
                                missing.append("\# of chips")


                            # -----------------------------------------
                            # Fab Notion: Top callout content (editable)
                            # -----------------------------------------
                            fab_top_note = st.text_area(
                                "Top Callout Editor : current text will be used unless edited",
                                value=_kv_get(fab_list, "Fab Top Callout"),
                                height=80,
                                placeholder="Patterning process : L0 Alignment marker, L1 Si trench (top-metal covered), L2 bottom-metal, L3 top-metal,  L4 airbridge hole, L5 airbridge bar",
                                key=f"fab_top_callout_{loaded_run_doc_id}",
                            )

                            payload = None
                            
                            fabin_date = (fabin or "").split(" ")[0]

                            if missing:
                                st.write("Error: belows are missing:\n- " + "\n- ".join(missing))
                            else:
                                payload = {
                                    "page_url": fab_notion_url,
                                    "num_chips": n_chips_int,
                                    "lot_id": lotid,
                                    "name": device_name,
                                    "fabin": fabin_date,
                                    "type": fab_type,
                                    "top_callout": fab_top_note,
                                }

                            create_clicked = st.button(
                                "Create",
                                key=f"btn_apply_fab_content_{loaded_run_doc_id}",
                            )

                            if create_clicked:

                                # -------------------------------------------------
                                # Write-once guard: prevent duplicate Fab creation
                                # -------------------------------------------------
                                fab_list = st.session_state.get("update_meta", {}).get("fab", [])
                                existing_child_ids = None

                                for it in fab_list:
                                    if (it.get("key") or "").strip() == "Fab Child Page IDs":
                                        existing_child_ids = it.get("value")
                                        break

                                already_created = existing_child_ids and len(existing_child_ids) > 0

                                if already_created:
                                    st.warning("Fab content already exists. Duplicate creation prevented.")

                                elif payload is None:
                                    st.warning("Fix missing fields above, then try again.")

                                else:
                                    # -----------------------------------------
                                    # Persist Fab Top Callout together with template
                                    # -----------------------------------------
                                    meta = st.session_state.setdefault("update_meta", {})
                                    fab_meta = meta.setdefault("fab", [])

                                    for it in fab_meta:
                                        if (it.get("key") or "") == "Fab Top Callout":
                                            it["value"] = fab_top_note
                                            break
                                    else:
                                        fab_meta.append({
                                            "key": "Fab Top Callout",
                                            "value": fab_top_note,
                                        })

                                    firestore_update_field(
                                        "runs",
                                        loaded_run_doc_id,
                                        "metadata.fab",
                                        fab_meta,
                                        id_token,
                                    )

                                    with st.spinner("Applying Fab content template (Notion)…"):
                                        result = add_fab_content(
                                            notion_token=st.secrets["notion"]["NOTION_TOKEN"],
                                            page_url=payload["page_url"],
                                            num_chips=payload["num_chips"],
                                            payload=payload,
                                            fabdata_db_urls=st.secrets["notion"]["NOTION_FABDATA_DB_URLS"],
                                            mode="all",
                                        )

                                    if result.get("success"):
                                        child_ids = result.get("fab_child_page_ids", [])

                                        if child_ids:
                                            fab_list = st.session_state.get("update_meta", {}).get("fab", [])

                                            already_has_ids = any(
                                                (it.get("key") or "").strip() == "Fab Child Page IDs"
                                                for it in fab_list
                                            )

                                            if not already_has_ids and child_ids:
                                                fab_list.append({
                                                    "key": "Fab Child Page IDs",
                                                    "value": child_ids,
                                                })

                                            firestore_update_field(
                                                "runs",
                                                loaded_run_doc_id,
                                                "metadata.fab",
                                                fab_list,
                                                id_token,
                                            )

                                        st.success("Fab content added and page IDs saved.")

                                    else:
                                        st.warning(f"Fab content failed: {result}")




                        elif target_meta == "package":
                            st.info("Package Notion content will be added later.")

                        else:  # measurement
                            st.info("Measurement Notion content will be added later.")


                    # ----------------------------------------------------
                    # ✅ SAVE BUTTONS (visible in this stage, outside sub-tabs)
                    # ----------------------------------------------------
                    # b1, b2, _ = st.columns([1, 1, 6])
                    b2, _ = st.columns([3, 5])

                    with b2:
                        label = "💾 Save"

                        if st.button(label, key=f"save_stage_{stage_key}"):

                            # if not loaded_run_no or loaded_run_no == "none":
                            #     st.warning("Please load/create the run first.")
                            #     st.stop()

                            if not loaded_run_doc_id:
                                st.warning("Please load/create the run first.")
                                st.stop()

                            # ----------------------------
                            # DESIGN: completed set/clear (same as before)
                            # ----------------------------
                            if target_layer == "design":
                                design_layer = next(
                                    (ly for ly in st.session_state["update_layers"]
                                     if (ly.get("layer_name", "").strip().lower() == "design")),
                                    None,
                                )
                                if not design_layer:
                                    st.error("Design layer not found.")
                                    st.stop()

                                chi = pytz.timezone("America/Chicago")
                                now_chi = datetime.now(chi).strftime("%Y-%m-%d %H:%M:%S")

                                design_progress = compute_layer_progress(design_layer)

                                ss_completed = next(
                                    (r for r in st.session_state["update_meta"]["design"]
                                     if r["key"].strip().lower() == "completed"),
                                    None,
                                )

                                override_on = st.session_state.get(
                                    f"ovr_design_completed_{loaded_run_doc_id}",  # <-- keep your checkbox key
                                    False
                                )

                                if ss_completed:
                                    if design_progress == 100:
                                        if not override_on:
                                            # ✅ only set if currently empty (prevents restamp on repeated Save)
                                            if not (ss_completed.get("value") or "").strip():
                                                ss_completed["value"] = now_chi
                                                firestore_update_field(
                                                    "runs",
                                                    # loaded_run_no,
                                                    loaded_run_doc_id,
                                                    "metadata.design.completed",
                                                    now_chi,
                                                    id_token,
                                                )
                                    else:
                                        if not override_on:
                                            # ✅ clear when <100 (but only if currently non-empty)
                                            if (ss_completed.get("value") or "").strip():
                                                ss_completed["value"] = ""
                                                firestore_update_field(
                                                    "runs",
                                                    # loaded_run_no,
                                                    loaded_run_doc_id,
                                                    "metadata.design.completed",
                                                    "",
                                                    id_token,
                                                )



                            # ----------------------------
                            # FAB: fabin/fabout logic (same as old code)
                            # ----------------------------
                            elif target_layer == "fabrication":
                                fab_layer = next(
                                    (ly for ly in st.session_state["update_layers"]
                                     if (ly.get("layer_name", "").strip().lower().startswith("fab")
                                         or ly.get("layer_name", "").strip().lower() == "fabrication")),
                                    None,
                                )
                                if not fab_layer:
                                    st.error("Fabrication layer not found.")
                                    st.stop()

                                chi = pytz.timezone("America/Chicago")
                                now_chi = datetime.now(chi).strftime("%Y-%m-%d %H:%M:%S")

                                fab_progress = compute_layer_progress(fab_layer)

                                fab_meta = st.session_state["update_meta"]["fab"]
                                fabin_row  = next((r for r in fab_meta if r["key"].strip().lower() == "fabin"), None)
                                fabout_row = next((r for r in fab_meta if r["key"].strip().lower() == "fabout"), None)

                                if fabout_row is None:
                                    st.error("Fabout row missing from FAB metadata")
                                    st.stop()

                                # # 🔒 RESET FABIN ONLY WHEN FAB PROGRESS IS 0
                                # if fab_progress == 0 and fabin_row and fabin_row.get("value"):
                                #     fabin_row["value"] = ""
                                #     firestore_update_field("runs", loaded_run_doc_id, "metadata.fab.fabin", "", id_token)

                                # 🔒 RESET FABIN ONLY WHEN ALL CHIPS ARE PENDING (true not-started state)
                                all_pending = all(
                                    (ch.get("status") or "").strip().lower() == "pending"
                                    for sub in fab_layer.get("substeps", [])
                                    for ch in sub.get("chips", [])
                                )

                                if all_pending and fabin_row and fabin_row.get("value"):
                                    fabin_row["value"] = ""
                                    firestore_update_field(
                                        "runs",
                                        loaded_run_doc_id,
                                        "metadata.fab.fabin",
                                        "",
                                        id_token,
                                    )

                                # FABIN — write once (earliest started_at)
                                if fabin_row and not fabin_row.get("value"):
                                    started_times = [
                                        ch.get("started_at")
                                        for sub in fab_layer.get("substeps", [])
                                        for ch in sub.get("chips", [])
                                        if ch.get("started_at")
                                    ]
                                    if started_times:
                                        fabin_time = min(started_times)
                                        fabin_row["value"] = fabin_time
                                        firestore_update_field("runs", loaded_run_doc_id, "metadata.fab.fabin", fabin_time, id_token)

                                override_fabout_on = st.session_state.get(f"ovr_fab_fabout_{loaded_run_doc_id}", False)

                                if fab_progress == 100:
                                    if not override_fabout_on:
                                        # ✅ only set if currently empty (prevents restamp on repeated Save)
                                        if not (fabout_row.get("value") or "").strip():
                                            fabout_row["value"] = now_chi
                                            firestore_update_field(
                                                "runs",
                                                # loaded_run_no,
                                                loaded_run_doc_id,
                                                "metadata.fab.fabout",
                                                now_chi,
                                                id_token,
                                            )
                                else:
                                    if not override_fabout_on:
                                        # ✅ clear when <100 (but only if currently non-empty)
                                        if (fabout_row.get("value") or "").strip():
                                            fabout_row["value"] = ""
                                            firestore_update_field(
                                                "runs",
                                                # loaded_run_no,
                                                loaded_run_doc_id,
                                                "metadata.fab.fabout",
                                                "",
                                                id_token,
                                            )


                            # ----------------------------
                            # PACKAGE: stage save uses the same logic as "Save Package Info"
                            # ----------------------------
                            elif target_layer == "package":
                                chip_uid = st.session_state.get("pkg_selected_chip_uid")
                                if not chip_uid:
                                    st.warning("Select a chip in Package Details first.")
                                    st.stop()

                                chip_meta_live = {
                                    "pcb_pic":  st.session_state.get(f"pkg_pcb_pic_{chip_uid}", ""),
                                    "bond_pic": st.session_state.get(f"pkg_bond_pic_{chip_uid}", ""),
                                    "pcb_type": st.session_state.get(f"pkg_pcb_type_{chip_uid}", ""),
                                    "notion":   st.session_state.get(f"pkg_notion_{chip_uid}", ""),
                                    "notes":    st.session_state.get(f"pkg_notes_{chip_uid}", ""),
                                }

                                save_package_info_core(
                                    chip_uid=chip_uid,
                                    chip_meta_live=chip_meta_live,
                                    fields=fields,
                                    update_layers=st.session_state["update_layers"],
                                    update_meta=st.session_state["update_meta"],
                                    loaded_run_doc_id=loaded_run_doc_id,
                                    id_token=id_token,
                                )

                                st.success("Package saved")
                                # st.rerun()

                            # ----------------------------
                            # MEASUREMENT: stage save uses the same logic as "Save Measurement Info"
                            # ----------------------------
                            elif target_layer == "measurement":
                                fridge_uid = st.session_state.get("meas_prev_fridge_uid")
                                if not fridge_uid:
                                    st.warning("Select a fridge in Measurement Details first.")
                                    st.stop()

                                fridge_meta_live = {
                                    "owner":    st.session_state.get(f"meas_owner_{loaded_run_doc_id}_{fridge_uid}", ""),
                                    "chip_uid": st.session_state.get(f"meas_chip_uid_{loaded_run_doc_id}_{fridge_uid}", ""),
                                    "cell_type": st.session_state.get(f"meas_cell_{loaded_run_doc_id}_{fridge_uid}", ""),
                                    # "notion":   st.session_state.get(f"meas_notion_{loaded_run_no}_{fridge_uid}", ""),
                                    "notes":    st.session_state.get(f"meas_notes_{loaded_run_doc_id}_{fridge_uid}", ""),
                                }

                                save_measure_info_core(
                                    fridge_uid=fridge_uid,
                                    fridge_meta_live=fridge_meta_live,
                                    fields=fields,
                                    update_layers=st.session_state["update_layers"],
                                    update_meta=st.session_state["update_meta"],
                                    loaded_run_doc_id=loaded_run_doc_id,
                                    id_token=id_token,
                                )

                                st.success("Measurement saved")
                                # st.rerun()

                            with st.spinner("Saving run and syncing Notion…"):
                                save_full_run(
                                    notion_source="status_save",
                                    notion_stage=target_layer,
                                )

                            st.success(f"{label.replace('💾 ', '')} saved")
                            st.rerun()
                            # st.stop()


# ------------------------------------------------------------
# 4. NOTION SETTING
# ------------------------------------------------------------
with r2c2:
    with st.expander("🛠 Notion Setting", expanded=False):
        # load_notion_templates_once()

        # tmpl = st.session_state["notion_templates"].setdefault("fab_create", {})

        tabs = st.tabs(["Design", "Fab", "Package", "Measure"])

        # ----------------- DESIGN TAB (placeholder for now) -----------------
        with tabs[0]:
            st.info("Design template settings will be added later.")

        # ----------------- FAB TAB (IMPLEMENT NOW) -----------------
        with tabs[1]:
            # st.markdown(
            #     "**Most properties are auto-managed by Fab Tracker.**  \n"
            #     "**The fields below are manually assigned at Fab page creation.**"
            # )
            st.info("Fab template settings will be added later.")



        # ----------------- PACKAGE TAB (placeholder for now) -----------------
        with tabs[2]:
            st.info("Package template settings will be added later.")

        # ----------------- MEASURE TAB (placeholder for now) -----------------
        with tabs[3]:
            st.info("Measurement template settings will be added later.")

