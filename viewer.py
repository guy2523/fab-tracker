# viewer.py  (clean, multi-layer grid with arrows)
import streamlit as st
import requests
# from firebase_client import auth, BASE_URL
from firebase_client import firebase_sign_in, BASE_URL
import streamlit.components.v1 as components


st.set_page_config(
    page_title="Fab Tracker - Viewer",
    page_icon="📡",
    layout="wide",
)


# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------



def get_num(field_dict, default=0):
    if not isinstance(field_dict, dict):
        return default
    if "integerValue" in field_dict:
        return int(field_dict["integerValue"])
    if "doubleValue" in field_dict:
        return float(field_dict["doubleValue"])
    return default


def parse_layers(fields):
    """Return normalized list of layers & substeps.

    Output format:
    [
      {
        "layer_name": str,
        "progress": int 0–100,
        "substeps": [
            {"name": str, "chips":[{name,status},...]},
        ]
      },
      ...
    ]
    """

    root = fields.get("steps", {}).get("arrayValue", {}).get("values", [])
    if not root:
        return []

    first = root[0]["mapValue"]["fields"]

    layers = []
    for lv in root:
        f = lv["mapValue"]["fields"]

        layer_name = f["layer_name"]["stringValue"]
        progress = get_num(f.get("progress", {}), 0)

        sub_raw = f["substeps"]["arrayValue"]["values"]
        substeps = []

        for sv in sub_raw:
            sm = sv["mapValue"]["fields"]
            sub_name = sm["name"]["stringValue"]

            # Chips inside substep
            chips = []
            chips_raw = sm.get("chips", {}).get("arrayValue", {}).get("values", [])
            for cv in chips_raw:
                cf = cv["mapValue"]["fields"]
                chips.append({
                    "name": cf["name"]["stringValue"],
                    "status": cf["status"]["stringValue"],
                })

            substeps.append({"name": sub_name, "chips": chips})

        # compute progress automatically
        all_chips = [c for s in substeps for c in s["chips"]]
        if progress == 0 and all_chips:
            done_count = sum(1 for c in all_chips if c["status"] == "done")
            progress = int(100 * done_count / len(all_chips))

        layers.append({
            "layer_name": layer_name,
            "progress": progress,
            "substeps": substeps,
        })

    return layers


def parse_metadata_section(section):
    """
    Converts Firestore metadata into ordered list of (key, value).
    Works for BOTH:
    - new array-based metadata
    - old map-based metadata
    """

    if not section:
        return []

    mv = section.get("mapValue", {}).get("fields", {})

    # ---- Case A: NEW FORMAT → array of {key, value} ----
    if "arrayValue" in mv:  # invalid; arrays do not appear inside mapValue
        pass

    # ---- Case A actual: the section itself might be an array ----
    if "arrayValue" in section:
        arr = section["arrayValue"].get("values", [])
        result = []
        for item in arr:
            fields = item["mapValue"]["fields"]
            k = fields["key"]["stringValue"]
            v = fields["value"]["stringValue"]
            result.append((k, v))
        return result

    # ---- Case B: OLD FORMAT → map of string fields ----
    if mv:
        result = []
        for k, v in mv.items():
            result.append((k, v.get("stringValue", "")))
        return result

    return []



def list_runs(id_token):
    url = f"{BASE_URL}/runs"
    r = requests.get(url, headers={"Authorization": f"Bearer {id_token}"})
    j = r.json()
    return j.get("documents", [])



import html as html_escape
def render_metadata_table(meta_list):

    rows = ""
    for i in range(0, len(meta_list), 2):
        k1, v1 = meta_list[i]
        k2, v2 = meta_list[i+1] if i+1 < len(meta_list) else ("","")

        # Escape + convert newlines to <br>
        v1 = html_escape.escape(v1).replace("\n", "<br>")
        v2 = html_escape.escape(v2).replace("\n", "<br>")
        k1 = html_escape.escape(k1)
        k2 = html_escape.escape(k2)

        rows += (
            f"<tr>"
            f"<td class='keycell'>{k1}</td>"
            f"<td class='valcell'>{v1}</td>"
            f"<td class='keycell'>{k2}</td>"
            f"<td class='valcell'>{v2}</td>"
            f"</tr>"
        )

    html = f"""
    <style>
        .keycell {{
            background-color: #f5f5f5;
            font-weight: 400;
            width: 20%;
        }}
        .valcell {{
            background-color: white;
            width: 30%;
        }}
        .meta-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .meta-table td {{
            border: 1px solid #e0e0e0;
            padding: 6px 8px;
        }}
    </style>

    <table class='meta-table'><tbody>
        {rows}
    </tbody></table>
    """

    return html


def firestore_to_python(v):
    if not isinstance(v, dict):
        return v

    # string
    if "stringValue" in v:
        return v["stringValue"]

    # int
    if "integerValue" in v:
        return int(v["integerValue"])

    # float
    if "doubleValue" in v:
        return float(v["doubleValue"])

    # bool
    if "booleanValue" in v:
        return bool(v["booleanValue"])

    # array (this was missing!)
    if "arrayValue" in v:
        arr = v["arrayValue"].get("values", [])
        return [firestore_to_python(x) for x in arr]

    # map
    if "mapValue" in v:
        return {
            kk: firestore_to_python(vv)
            for kk, vv in v["mapValue"].get("fields", {}).items()
        }

    return v


def get_meta_value(meta_list, target_key):
    """Returns value for matching key from metadata list of dicts."""
    if not isinstance(meta_list, list):
        return ""
    for item in meta_list:
        if item.get("key") == target_key:
            return item.get("value", "")
    return ""


def get_meta_date(meta_data_child: str, target_key: str):

    # Load metadata
    meta = fields.get("metadata", {}).get("mapValue", {}).get("fields", {})
    meta_child = meta.get(meta_data_child, {}).get("arrayValue", {}).get("values", [])

    # Convert Firestore objects → Python dict list
    meta_child_py = [firestore_to_python(v) for v in meta_child]

    # Extract date
    date = get_meta_value(meta_child_py, target_key)

    return date




# ------------------------------------------------------------
# Chip HTML (horizontal, color-coded)
# ------------------------------------------------------------

def substep_chip_html(chip):
    status = chip["status"].lower()

    if status == "done":
        bg, fg = "#d4edda", "#155724"
    elif status == "in_progress":
        bg, fg = "#fff3cd", "#856404"
    else:
        bg, fg = "#eeeeee", "#555555"

    return (
        f"<span class='layer-chip' "
        f"style='background:{bg};color:{fg};'>"
        f"{chip['name']}"
        "</span>"
    )


# ------------------------------------------------------------
# Layer card (title + bar + substeps)
# ------------------------------------------------------------

def layer_card_html(layer, idx=None):
    if idx is not None:
        title_prefix = f"{idx + 1}. "
    else:
        title_prefix = ""

    progress = int(layer.get("progress", 0))

    # title row
    title_html = (
        f"{title_prefix}{layer['layer_name']} ({progress}%)"
        f"<span class='step-mini-bar'>"
        f"<span class='step-mini-fill' style='width:{progress}%;'></span>"
        f"</span>"
    )

    # substeps expanded
    body_html = ""
    for sub in layer["substeps"]:
        sub_name = sub["name"]
        chips_html = " ".join(substep_chip_html(c) for c in sub["chips"])

        body_html += (
            f"<div style='margin-top:3px;margin-bottom:2px;'>"
            f"<div style='font-size:0.80rem; font-weight:600; color:#333;'>{sub_name}</div>"
            f"<div class='layer-chip-container'>{chips_html}</div>"
            f"</div>"
        )

    return (
        "<div class='layer-card'>"
        f"<div class='layer-card-title'>{title_html}</div>"
        f"{body_html}"
        "</div>"
    )


# ------------------------------------------------------------
# Viewer login
# ------------------------------------------------------------

# if "viewer_user" not in st.session_state:
#     st.header("🔐 Viewer Login")
#     email = st.text_input("Email")
#     pw = st.text_input("Password", type="password")
#     if st.button("Login"):
#         try:
#             u = auth.sign_in_with_email_and_password(email, pw)
#             st.session_state.viewer_user = u
#             st.rerun()
#         except Exception as e:
#             st.error(str(e))
#     st.stop()

if "viewer_user" not in st.session_state:
    st.header("🔐 Viewer Login")
    email = st.text_input("Email")
    pw = st.text_input("Password", type="password")

    if st.button("Login"):
        try:
            u = firebase_sign_in(email, pw)   # REST SIGN-IN
            st.session_state.viewer_user = u
            st.rerun()
        except Exception as e:
            st.error(f"Login failed: {e}")

    st.stop()


u = st.session_state.viewer_user
token = u["idToken"]
email = u["email"]

st.sidebar.write("Logged in as:", email)
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()



# ---------------- TOP BAR ----------------
top_left, top_right = st.columns([1, 1])

with top_left:
    st.markdown(
    "<h1 style='margin-bottom:-50px;'>🔍 Run Tracker</h1>",
    unsafe_allow_html=True,
    )


with top_right:
    st.write("")  # small vertical alignment shift

    # Two columns: refresh button + combined legend
    legend_col, refresh_col = st.columns([0.5, 0.1])

    # --- Refresh Button ---
    with refresh_col:
        if st.button("🔄 Refresh"):
            st.rerun()

    # --- Combined Legend (completed + in-progress) ---
    with legend_col:
        st.markdown("""
<div style="display:flex; align-items:center; justify-content:flex-end; gap:18px;">

  <div style="display:flex; align-items:center; gap:4px;">
    <span style="width:10px; height:10px; background:#4caf50;
                 border-radius:50%; display:inline-block;"></span>
    <span style="font-size:1rem;">completed</span>
  </div>

  <div style="display:flex; align-items:center; gap:4px;">
    <span style="width:10px; height:10px; background:#ffd54f;
                 border-radius:50%; display:inline-block;"></span>
    <span style="font-size:1rem;">in-progress</span>
  </div>

</div>
        """, unsafe_allow_html=True)






# ------------------------------------------------------------
# CSS
# ------------------------------------------------------------

st.markdown("""
<style>
.run-card {
    border: 1px solid #ddd;
    border-radius: 10px;
    background: #fafafa;
    padding: 14px;
    margin-bottom: 10px;
    margin-top: 10px;
}
</style>
""", unsafe_allow_html=True)



st.markdown("""
<style>

.layer-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 12px;
}

.step-block {
    display: flex;
    align-items: center;
    gap: 6px;
}

.layer-card {
    border: 1px solid #ddd;
    border-radius: 10px;
    padding: 10px;
    background: #fafafa;
    width: 340px;
    min-height: 120px;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
}

.layer-card-title {
    font-weight: 600;
    margin-bottom: 4px;
    font-size: 0.90rem;
    line-height: 1.1;
}

.layer-chip-container {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
}

.layer-chip {
    padding: 0px 6px;
    border-radius: 8px;
    font-size: 0.78rem;
    white-space: nowrap;
}

.arrow-cell {
    width: 18px;
    text-align: center;
    font-size: 1.1rem;
    color: #999;
}

.step-mini-bar {
    width: 60px;
    height: 10px;
    background: #e0e0e0;
    border-radius: 4px;
    overflow: hidden;
    display: inline-block;
    vertical-align: middle;
    margin-left: 6px;
}

.step-mini-fill {
    display: block;
    height: 100%;
    background: #555;
}

</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------
# Fetch & Display Runs
# ------------------------------------------------------------



runs = list_runs(token)
if not runs:
    st.info("No runs found.")
    st.stop()


# # Helper to extract Fabin/Fabout dates from metadata
# def get_meta_date_for_filter(fields, meta_key):
#     meta = fields.get("metadata", {}).get("mapValue", {}).get("fields", {})
#     fab = meta.get("fab", {}).get("arrayValue", {}).get("values", [])
#     fab_list = firestore_to_python(meta.get("fab", {})) if isinstance(fab, list) else []

#     for item in fab_list:
#         if item["key"] == meta_key:
#             return item["value"]
#     return ""
    


# # ----- FILTER EXPANDER (aligned left) -----
# left, _ = st.columns([0.25, 0.75])   # 25% width column for the filter card

# with left:
#     with st.expander("🔍 Filter Runs", expanded=False):
#         f_col1, f_col2 = st.columns(2)
#         with f_col1:
#             run_filter = st.text_input("Run ID contains…", "")
#         with f_col2:
#             device_filter = st.text_input("Device name contains…", "")

#         d1, d2 = st.columns(2)
#         with d1:
#             fabin_after = st.date_input("Fab-in after…", value=None)
#         with d2:
#             fabout_before = st.date_input("Fab-out before…", value=None)

#         apply_btn = st.button("Apply Filters")


# # ----- FILTER EXPANDER (aligned left) -----
# left, _ = st.columns([0.25, 0.75])   # 25% width column for the filter card

# with left:
#     with st.expander("🔍 Filter Runs", expanded=False):
#         f_col1, f_col2 = st.columns(2)
#         with f_col1:
#             run_filter = st.text_input("Run ID contains…", "")
#         with f_col2:
#             device_filter = st.text_input("Device name contains…", "")

#         d1, d2 = st.columns(2)
#         with d1:
#             fabin_after = st.date_input("Fab-in after…", value=None)
#         with d2:
#             fabout_before = st.date_input("Fab-out before…", value=None)

#         c1, c2 = st.columns([1,1])
#         with c1:
#             apply_btn = st.button("Apply Filters")
#         with c2:
#             reset_btn = st.button("Reset Filters")


def get_meta_date_for_filter(fields, meta_data_child, target_key):
    # Load metadata
    meta = fields.get("metadata", {}).get("mapValue", {}).get("fields", {})
    meta_child = meta.get(meta_data_child, {}).get("arrayValue", {}).get("values", [])

    # Convert Firestore arrayValue → python
    meta_child_py = [firestore_to_python(v) for v in meta_child]

    # Extract target entry
    return get_meta_value(meta_child_py, target_key)



# ----- FILTER EXPANDER (aligned left) -----
left, _ = st.columns([0.25, 0.75])

with left:
    with st.expander("🔍 Filter Runs", expanded=False):
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            run_filter = st.text_input(
                "Run ID contains…",
                "",
                key="run_filter"        # ← minimal change ①
            )
        with f_col2:
            device_filter = st.text_input(
                "Device name contains…",
                "",
                key="device_filter"     # ← minimal change ②
            )

        d1, d2 = st.columns(2)
        with d1:
            fabin_after = st.date_input(
                "Fab-in after…",
                value=None,
                key="fabin_after"        # ← minimal change ③
            )
        with d2:
            fabout_before = st.date_input(
                "Fab-out before…",
                value=None,
                key="fabout_before"      # ← minimal change ④
            )

        c1, c2 = st.columns([1,1])
        with c1:
            apply_btn = st.button("Apply Filters")
        with c2:
            reset_btn = st.button("Reset Filters")

# # ---- RESET BEHAVIOR (minimal) ----
# if reset_btn:
#     st.session_state.run_filter = ""
#     st.session_state.device_filter = ""
#     st.session_state.fabin_after = None
#     st.session_state.fabout_before = None
#     st.rerun()            # ← ensures UI fields visually clear


# ---- RESET BEHAVIOR (safe for Streamlit Cloud) ----
if reset_btn:
    st.session_state.update({
        "run_filter": "",
        "device_filter": "",
        "fabin_after": None,
        "fabout_before": None,
    })
    st.rerun()



# ------------------------------------------------------------
# APPLY FILTER LOGIC
# ------------------------------------------------------------

def matches_filters(fields):
    run_no = fields["run_no"]["stringValue"]
    device = fields["device_name"]["stringValue"]

    # metadata dates
    fabin_str  = get_meta_date_for_filter(fields, "fab", "Fabin")
    fabout_str = get_meta_date_for_filter(fields, "fab", "Fabout")

    # convert date
    import datetime
    def to_date(s):
        try:
            return datetime.datetime.strptime(s, "%Y-%m-%d").date()
        except:
            return None

    fabin_date  = to_date(fabin_str)
    fabout_date = to_date(fabout_str)

    # apply filters
    if run_filter and run_filter.lower() not in run_no.lower():
        return False

    if device_filter and device_filter.lower() not in device.lower():
        return False

    if fabin_after and fabin_date and fabin_date < fabin_after:
        return False

    if fabout_before and fabout_date and fabout_date > fabout_before:
        return False

    return True



# ---- NEW: minimal reset behavior ----
if reset_btn:
    run_filter = ""
    device_filter = ""
    fabin_after = None
    fabout_before = None
    # simply show all runs (no rerun needed)
    filtered_runs = runs
else:
    filtered_runs = [doc for doc in runs if matches_filters(doc["fields"])]





# Filter result
if apply_btn:
    filtered_runs = [doc for doc in runs if matches_filters(doc["fields"])]
else:
    filtered_runs = runs



# --- Sort runs by run_no descending (e.g. 003 > 002 > 001) ---
filtered_runs.sort(key=lambda d: d["fields"]["run_no"]["stringValue"], reverse=True)

for doc in filtered_runs:
    fields = doc["fields"]
    run_no = fields["run_no"]["stringValue"]
    device = fields["device_name"]["stringValue"]
    created_date = fields["created_date"]["stringValue"]
    creator = fields["creator"]["stringValue"]


    layers = parse_layers(fields)

    total = sum(len(s["chips"]) for l in layers for s in l["substeps"])
    done = sum(
        1
        for l in layers
        for s in l["substeps"]
        for c in s["chips"]
        if c["status"] == "done"
    )
    overall = done / total if total else 0

    layers_html = ""
    for idx, layer in enumerate(layers):
        layers_html += "<div class='step-block'>"
        layers_html += layer_card_html(layer, idx)
        if idx < len(layers) - 1:
            layers_html += "<div class='arrow-cell'>➜</div>"
        layers_html += "</div>"

    design_date = get_meta_date("design", "Completed")
    fab_in = get_meta_date("fab", "Fabin")
    fab_out = get_meta_date("fab", "Fabout")

    html = (
        "<div>"
        # f"<h4 style='margin:0 0 4px 0;'>Run: {run_no}</h4>"

        # ---------------- METADATA + RIGHT-ALIGNED BAR ----------------
        "<div style='display:flex; align-items:center; justify-content:space-between; width:100%;'>"

            # LEFT SIDE: metadata fields
            "<div style='font-size:0.9rem; white-space:nowrap;'>"
            f"  <span style='color:#555; font-weight:400;'>Created {created_date}</span> "
            f"|  <span style='color:#555; font-weight:400;'>{device}</span> "
            f"| <span style='color:#555; font-weight:400;'>Design {design_date}</span> "
            f"| <span style='color:#555; font-weight:400;'>Fab {fab_in} ➜ {fab_out}</span>  "
            "</div>"

            # RIGHT SIDE: progress label + bar
            "<div style='display:flex; align-items:center; gap:8px; flex:1; margin-left:20px;'>"
                "<div style='font-size:0.85rem; font-weight:600; white-space:nowrap;'>Overall:</div>"
                "<div style='width:30%; height:12px; background:#eee; border-radius:999px; overflow:hidden;'>"
                    f"<div style='width:{overall*100}%; height:100%; background:#4caf50;'></div>"
                "</div>"
            "</div>"

        "</div>"
        # ---------------------------------------------------------------

        # 🔥 RED LINE ADDED HERE
        "<div style='width:100%; height:4px; background:#eee; margin:10px 0 20px 0;'></div>"

        "<div class='layer-grid'>"
        f"{layers_html}"
        "</div>"
        "</div>"
    )



    # One container per run
    # One expandable wrapper per run
    with st.expander(f"Run {run_no} / {device} / fab {fab_in} ➜ {fab_out}", expanded=False):
    # with st.container():

        # Run card boundary
        st.markdown("<div class='run-card'>"+html+"</div>", unsafe_allow_html=True)


        # -------- Metadata tables -------  -
        meta = fields.get("metadata", {}).get("mapValue", {}).get("fields", {})
        design_meta  = parse_metadata_section(meta.get("design", {}))
        fab_meta     = parse_metadata_section(meta.get("fab", {}))
        package_meta = parse_metadata_section(meta.get("package", {}))
        measure_meta = parse_metadata_section(meta.get("measure", {}))


### 2x 2 grid expaders

        # First row
        row1_col1, row1_col2 = st.columns([1, 1])
        with row1_col1:
            with st.expander("🎨 Design", expanded=False):
                st.markdown(render_metadata_table(design_meta), unsafe_allow_html=True)

        with row1_col2:
            with st.expander("⚡ Fab", expanded=False):
                st.markdown("<div>*PIC : Person in charge</div>", unsafe_allow_html=True)
                st.markdown(render_metadata_table(fab_meta), unsafe_allow_html=True)


        # Second row
        row2_col1, row2_col2 = st.columns([1, 1])
        with row2_col1:
            with st.expander("𓇲 Package", expanded=False):
                st.markdown("<div>*PIC : Person in charge</div>", unsafe_allow_html=True)
                st.markdown(render_metadata_table(package_meta), unsafe_allow_html=True)

        with row2_col2:
            with st.expander("📈 Measure", expanded=False):
                st.markdown("<div>*PIC : Person in charge</div>", unsafe_allow_html=True)
                st.markdown(render_metadata_table(measure_meta), unsafe_allow_html=True)


