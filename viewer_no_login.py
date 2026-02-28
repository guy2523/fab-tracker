# viewer.py  (clean, multi-layer grid with arrows)
import streamlit as st
import requests
from firebase_client import firebase_sign_in_with_google, BASE_URL, firebase_refresh_id_token
import streamlit.components.v1 as components
import copy
import time
import html as html_escape
from core.metadata import get_measure_fridges
from ui.metadata_ui import format_range
import urllib.parse

if "force_reset" not in st.session_state:
    st.session_state.clear()
    st.session_state["force_reset"] = True
    st.rerun()


def build_measurement_fridge_display_labels(layers: list) -> dict:
    """
    Build viewer-consistent Measurement fridge labels from flow order.

    Returns:
        dict[str, str]: fridge_uid -> display label
        e.g. {"fridge_xxx": "Bluefors (2)"}
    """

    ordered_uids = []
    base_labels = []

    for layer in layers:
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

    # Count occurrences
    label_counts = {}
    for lbl in base_labels:
        label_counts[lbl] = label_counts.get(lbl, 0) + 1

    # Build display labels
    label_indices = {}
    fridge_display_label = {}

    for uid, lbl in zip(ordered_uids, base_labels):
        if label_counts[lbl] > 1:
            label_indices[lbl] = label_indices.get(lbl, 0) + 1
            fridge_display_label[uid] = f"{lbl} ({label_indices[lbl]})"
        else:
            fridge_display_label[uid] = lbl

    return fridge_display_label


def collect_dashboard_events_from_metadata(*, fields: dict, layers: list) -> list[dict]:
    """
    Build dashboard events from Firestore metadata only.
    Priority first, recency second.
    Returns a list of dicts with keys:
      - priority (int)
      - timestamp (str, ISO or YYYY-MM-DD)
      - message (str)
    """

    events = []

    # ------------------------------------------------------------
    # Parse metadata (authoritative source)
    # ------------------------------------------------------------
    meta = (
        fields.get("metadata", {})
              .get("mapValue", {})
              .get("fields", {})
    )

    design_meta  = parse_metadata_section(meta.get("design", {}))
    fab_meta     = parse_metadata_section(meta.get("fab", {}))
    package_meta = firestore_to_python(meta.get("package", {}))
    measure_meta = firestore_to_python(meta.get("measure", {}))

    # ------------------------------------------------------------
    # Design
    # ------------------------------------------------------------
    design_completed = (get_meta_data(fields, "design", "Completed") or "").strip()


    if design_completed:
        events.append({
            "priority": 3,  # lowest
            "timestamp": design_completed,
            "message": f"Design finished on {date_only(design_completed)}",
        })

    # ------------------------------------------------------------
    # Fabrication
    # ------------------f------------------------------------------

    fab_in  = (get_meta_data(fields, "fab", "Fabin") or "").strip()
    fab_out = (get_meta_data(fields, "fab", "Fabout") or "").strip()

    if fab_in:
        events.append({
            "priority": 2,
            "timestamp": fab_in,
            "message": f"Fabrication started on {date_only(fab_in)}",
        })

    if fab_out:
        events.append({
            "priority": 2,
            "timestamp": fab_out,
            "message": f"Fabrication finished on {date_only(fab_out)}",
        })

    # ------------------------------------------------------------
    # Package (chip-centric)
    # ------------------------------------------------------------
    chips = (package_meta or {}).get("chips", {}) or {}

    # (optional) if package_meta is *already* the chips dict in some runs, support that too
    if "chips" not in (package_meta or {}) and isinstance(package_meta, dict):
        # heuristic: keys look like chip_xxx
        if any(k.startswith("chip_") for k in package_meta.keys()):
            chips = package_meta


    # st.write(f"DEBUG {chips}")
    chip_uid_to_label = get_package_chips(layers)

    for chip_uid, c in chips.items():
        if not isinstance(c, dict):
            continue

        chip_label = chip_uid_to_label.get(chip_uid, chip_uid)

        pcb_ready = (c.get("pcb_ready") or "").strip()
        if pcb_ready:
            events.append({
                "priority": 1,
                "timestamp": pcb_ready,
                "message": f"{chip_label} PCB ready on {date_only(pcb_ready)}",
            })

        bond_date = (c.get("bond_date") or "").strip()
        if bond_date:
            events.append({
                "priority": 1,
                "timestamp": bond_date,
                "message": f"{chip_label} bonded on {date_only(bond_date)}",
            })

        delivery = (c.get("delivery") or "").strip()
        delivery_time = (c.get("delivery_time") or "").strip()
        if delivery and delivery_time:
            events.append({
                "priority": 1,
                "timestamp": delivery_time,
                "message": f"{chip_label} delivered to {delivery} on {date_only(delivery_time)}",
            })

    # ------------------------------------------------------------
    # Measurement (fridge-centric)
    # ------------------------------------------------------------
    fridges = (measure_meta or {}).get("fridges", {}) or {}

    # Use flow-derived labels (Bluefors (1), Bluefors (2), ...)
    # raw_fridges = get_measure_fridges(layers)

    fridge_display_label = build_measurement_fridge_display_labels(layers)


    for fridge_uid, f in fridges.items():
        if not isinstance(f, dict):
            continue

        cooldown_start = (f.get("cooldown_start") or "").strip()
        if not cooldown_start:
            continue

        label = fridge_display_label.get(fridge_uid, "Measurement")

        events.append({
            "priority": 0,  # highest
            "timestamp": cooldown_start,
            "message": f"{label} cooldown started on {date_only(cooldown_start)}",
        })

    # ------------------------------------------------------------
    # Sort: priority first, recency second
    # ------------------------------------------------------------
    events.sort(
        key=lambda e: (e["priority"], e["timestamp"]),
        reverse=False,
    )

    return events


def _meas_notion_label(fridge_label: str, cooldown_start: str) -> str:
    lab = (fridge_label or "").strip().lower()

    # extract YYMMDD from "YYYY-MM-DD ..." or ISO
    yymmdd = ""
    s = (cooldown_start or "").strip()
    if s:
        yymmdd = s.replace("-", "")[2:8]  # 2026-02-02 -> 260202

    if "ice" in lab:      # ICEOxford
        return f"IO[{yymmdd}]" if yymmdd else "IO"

    if "blue" in lab:     # Bluefors
        return f"BF{yymmdd}" if yymmdd else "BF"

    return "Notion"



def measurement_has_started(layers, fields):
    """
    Measurement is considered started if ANY fridge has real activity.
    This is a lifecycle latch, NOT progress-based.
    Source of truth: Firestore metadata.measure.fridges
    """
    meta = (
        fields.get("metadata", {})
              .get("mapValue", {})
              .get("fields", {})
              .get("measure", {})
              .get("mapValue", {})
              .get("fields", {})
              .get("fridges", {})
              .get("mapValue", {})
              .get("fields", {})
    )

    for fridge_uid, fridge_fs in meta.items():
        f = firestore_to_python(fridge_fs)

        if (
            f.get("cooldown_start")
            or f.get("measure_start")
            or f.get("warmup_start")
        ):
            return True

    return False



def date_only(dt_str):
    if not dt_str:
        return ""
    # works for "YYYY-MM-DD HH:MM:SS" and ISO strings
    return dt_str.split(" ")[0]



def meta_to_rows(meta_list):
    """
    meta_list: list of (key, value) tuples
    → rows for st.dataframe
    """
    rows = []

    for key, value in meta_list:
        # 🔒 unwrap Firestore leftovers if any
        if isinstance(value, dict):
            if "timestampValue" in value:
                value = value["timestampValue"]
            elif "stringValue" in value:
                value = value["stringValue"]
            elif "integerValue" in value:
                value = int(value["integerValue"])
            elif "doubleValue" in value:
                value = float(value["doubleValue"])
            elif "booleanValue" in value:
                value = bool(value["booleanValue"])

        # normalize empties
        if value is None:
            value = ""

        rows.append({
            "Field": key,
            "Value": value,
        })

    return rows


def design_meta_to_row(design_meta):
    """
    design_meta: list of {"key","value"} OR list of (key,value)
    Returns: a single dict row for st.dataframe
    """
    # normalize to pairs
    if design_meta and isinstance(design_meta[0], dict):
        pairs = [(x.get("key", ""), x.get("value", "")) for x in design_meta]
    else:
        pairs = list(design_meta or [])

    # flatten into dict (last wins)
    d = {}
    for k, v in pairs:
        key = (str(k) or "").strip()
        val = v

        # unwrap Firestore leftovers if needed
        if isinstance(val, dict):
            if "timestampValue" in val:
                val = val["timestampValue"]
            elif "stringValue" in val:
                val = val["stringValue"]
            elif "integerValue" in val:
                val = int(val["integerValue"])
            elif "doubleValue" in val:
                val = float(val["doubleValue"])
            elif "booleanValue" in val:
                val = bool(val["booleanValue"])

        d[key] = format_value_auto("" if val is None else val)

    # Build download link for File column (using FileId + FileName when present)
    file_id = d.get("FileId") or d.get("Filed") or ""
    file_name = d.get("FileName") or ""
    if file_id:
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        label = file_name or "design file"
        # d["File"] = f"{url}#Download file – {label}"
        d["File"] = f"{url}# {label}"


    # optional: hide internal keys in this table
    d.pop("FileId", None)
    d.pop("Filed", None)
    d.pop("FileName", None)

    return d

def extract_fab_attachments(fab_meta):
    """
    Viewer-side parser for Fab attachments.
    Supports:
      - legacy: FileId + FileName (single)
      - multi:  FileId_1/FileName_1, FileId_2/FileName_2, ...
    Returns: list of {"id","name"} in display order.
    """
    if not fab_meta:
        return []

    # normalize meta_list -> dict
    if isinstance(fab_meta, list) and fab_meta and isinstance(fab_meta[0], dict):
        pairs = [(x.get("key", ""), x.get("value", "")) for x in fab_meta]
    else:
        pairs = list(fab_meta or [])

    d = {}
    for k, v in pairs:
        d[(str(k) or "").strip()] = v

    files = []

    # ---- multi keys: FileId_1, FileName_1, ...
    idx = 1
    found_any_numbered = False
    while True:
        fid = d.get(f"FileId_{idx}", "") or ""
        name = d.get(f"FileName_{idx}", "") or ""
        if fid:
            found_any_numbered = True
            files.append({"id": str(fid), "name": str(name or "")})
            idx += 1
            continue
        # stop when sequence breaks (common case)
        break

    # ---- fallback legacy single file
    if not files and not found_any_numbered:
        fid = d.get("FileId") or d.get("Filed") or ""
        name = d.get("FileName") or ""
        if fid:
            files.append({"id": str(fid), "name": str(name or "")})

    return files


def drive_download_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def format_range_compact(start, end):
    def to_ymd(v):
        if not v:
            return None
        y, m, d = v.split(" ")[0].split("-")
        return f"{y[2:]}/{m}/{d}"

    s = to_ymd(start)
    e = to_ymd(end)

    if not s and not e:
        return ""

    if s and not e:
        return f"{s} -"

    if e and not s:
        return f"- {e}"

    return f"{s} - {e}"



def format_date_compact(v):
    if not v:
        return ""
    y, m, d = v.split(" ")[0].split("-")
    return f"{y[2:]}/{m}/{d}"


def format_value_auto(v):
    if isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-":
        return format_date_compact(v)
    return v




st.set_page_config(
    page_title="Fab Tracker - Viewer",
    page_icon="📡",
    layout="wide",
)

# ------------------------------------------------------------
# CSS
# ------------------------------------------------------------



# st.markdown("""
# <style>
# .run-card {
#     border: 1px solid var(--secondary-background-color);
#     border-radius: 10px;
#     background: var(--secondary-background-color);
#     color: var(--text-color);
#     padding: 14px;
#     margin-bottom: 10px;
#     margin-top: 10px;
# }
# </style>
# """, unsafe_allow_html=True)

st.markdown("""
<style>
.header-right span {
    white-space: nowrap;
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
    align-items: flex-start;
}

.step-block {
    display: flex;
    align-items: center;
    gap: 6px;
}

.layer-card {
    border: 1px solid rgba(128, 128, 128, 0.35);
    box-shadow: 0 0 0 1px rgba(0,0,0,0.04);
    border-radius: 10px;
    padding: 10px;
    background: transparent;
    color: var(--text-color);
    width: 280px;
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
    padding: 0px 4px;
    border-radius: 8px;
    font-size: 0.78rem;
    white-space: nowrap;
}

.arrow-cell {
    width: 10px;
    text-align: center;
    font-size: 0.9rem;
    color: #999;
}

.step-mini-bar {
    width: 50px;
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

st.markdown("""
<style>
/* collapsed completed run */
div[data-testid="stExpander"] .completed-run-header {
    opacity: 0.45;
    transition: opacity 0.25s ease;
}

/* expanded → full opacity */
div[data-testid="stExpander"][aria-expanded="true"] .completed-run-header {
    opacity: 1.0 !important;
}
</style>
""", unsafe_allow_html=True)


st.markdown("""
<style>
.layer-card.done-layer {
    border: 1.5px solid rgba(76, 175, 80, 0.65);
    background-color: rgba(76, 175, 80, 0.12);
}

.layer-card.progress-layer {
    border: 1.5px solid rgba(244, 197, 66, 0.65);
    background-color: rgba(244, 197, 66, 0.12);
}
</style>
""", unsafe_allow_html=True)


st.markdown("""
<style>
/* Remove ALL top padding from Streamlit main container */
div.block-container {
    padding-top: 0.2rem !important;   /* was ~3–4rem */
    margin-top: 0 !important;
}

/* Optional: tighten spacing between rows globally */
div.block-container > div {
    margin-top: 0rem !important;
}
</style>
""", unsafe_allow_html=True)


st.markdown("""
<style>

/* ==========================
   BASE CLASS (shared styles)
   ========================== */
.fab-progress {
    position: relative;
    border-radius: 5px;
    overflow: hidden;
    background: #e0e0e0;  /* light gray track */
}

/* ==========================
   HEIGHT & WIDTH VARIANTS
   ========================== */

/* Overall progress bar */
.fab-progress.overall {
    height: 14px;     /* 👈 overall height */
    width: 55%;     /* 👈 overall width (customize freely) */
}

/* Layer progress bars */
.fab-progress.layer {
    height: 10px;     /* 👈 layer height */
    width: 240px;     /* 👈 layer width */
}

/* Chip progress bars (optional) */
.fab-progress.chip {
    height: 6px;      /* 👈 chip height */
    width: 160px;     /* 👈 chip width */
}

/* ==========================
   Completed (static fill)
   ========================== */
.fab-progress-fill-complete {
    height: 100%;
    background: #555;
    transition: width 0.25s ease;
}

/* ==========================
   In-progress (animated stripes)
   ========================== */
.fab-progress-fill-flow {
    height: 100%;
    background: repeating-linear-gradient(
        45deg,
        #555 0px,
        #555 12px,
        #777 12px,
        #777 24px
    );
    background-size: 24px 24px;
    animation: fabStripe 0.8s linear infinite;
    transition: width 0.25s ease;
}

/* Seamless rightward motion */
@keyframes fabStripe {
    from { background-position: 0 0; }
    to   { background-position: 24px 0; }
}

</style>
""", unsafe_allow_html=True)




from streamlit_autorefresh import st_autorefresh

# Auto-refresh every 5 seconds (10000 ms)
st_autorefresh(interval=10000, key="auto_refresh")

# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------

def render_package_table_clean(package_meta, chip_labels, layers):
# def render_package_table_clean(package_meta, chip_labels, package_storage=""):
    rows = []

    for chip_uid, label in chip_labels.items():
        meta = package_meta.get(chip_uid, {})


        # -----------------------------------
        # Termination override (Option A - viewer only)
        # -----------------------------------
        pcb_display = format_date_compact(meta.get("pcb_ready", ""))
        bond_display = format_date_compact(meta.get("bond_date", ""))
        delivery_display = format_date_compact(meta.get("delivery_time", ""))

        for layer in layers:
            if layer.get("layer_name", "").lower() != "package":
                continue

            for sub in layer.get("substeps", []):
                if sub.get("chip_uid") != chip_uid:
                    continue

                for chip in sub.get("chips", []):
                    name = (chip.get("name") or "").lower()
                    status = (chip.get("status") or "").lower()

                    if status != "terminate":
                        continue

                    if "pcb" in name:
                        pcb_display = "terminated"

                    elif "bond" in name:
                        bond_display = "terminated"

                    elif "delivery" in name:
                        delivery_display = "terminated"


        rows.append({
            "Chip": label,
            "PCB Owner": meta.get("pcb_pic", ""),
            "PCB Type": meta.get("pcb_type", ""),
            # "PCB Ready": format_date_compact(meta.get("pcb_ready", "")),
            "PCB Ready": pcb_display,
            "Bond Owner": meta.get("bond_pic", ""),
            # "Bond Date": format_date_compact(meta.get("bond_date", "")),
            "Bond Date": bond_display,
            "Delivery": meta.get("delivery", ""),   # ✅ per-chip
            # "Delivery Date": format_date_compact(meta.get("delivery_time", "")),  # ✅ new
            "Delivery Date": delivery_display,
            "Notion": meta.get("notion", ""),
            "Notes": meta.get("notes", ""),
        })

    return rows



def get_package_chips(layers):
    """
    Extract {chip_uid: label} from Package layer.
    Label is display-only (C01, C02, etc).
    """
    chip_map = {}

    for layer in layers:
        if layer.get("layer_name") != "Package":
            continue

        for sub in layer.get("substeps", []):
            chip_uid = sub.get("chip_uid")
            if not chip_uid:
                continue

            label = sub.get("label") or sub.get("name") or "Unknown"
            chip_map[chip_uid] = label

    return chip_map


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
            # sub_name = sm["name"]["stringValue"]
            sub_name = (
                sm.get("label", {}).get("stringValue")
                or sm.get("name", {}).get("stringValue")
                or "Unknown"
            )

            # Chips inside substep
            chips = []
            chips_raw = sm.get("chips", {}).get("arrayValue", {}).get("values", [])
            for cv in chips_raw:
                cf = cv["mapValue"]["fields"]
                # chips.append({
                #     "name": cf["name"]["stringValue"],
                #     "status": cf["status"]["stringValue"],
                # })

                chip_obj = {
                    "name": cf["name"]["stringValue"],
                    "status": cf["status"]["stringValue"],
                }

                # Load timestamp fields if they exist
                if "started_at" in cf:
                    chip_obj["started_at"] = cf["started_at"]["stringValue"]

                if "completed_at" in cf:
                    chip_obj["completed_at"] = cf["completed_at"]["stringValue"]

                chips.append(chip_obj)

            substep_obj = {
                "name": sub_name,
                "label": sub_name,
                "chips": chips,
            }

            # Preserve chip identity (Package)
            if "chip_uid" in sm:
                substep_obj["chip_uid"] = sm.get("chip_uid", {}).get("stringValue")

            # Preserve fridge identity (Measurement)
            if "fridge_uid" in sm:
                substep_obj["fridge_uid"] = sm.get("fridge_uid", {}).get("stringValue")

            substeps.append(substep_obj)

        all_chips = [c for s in substeps for c in s["chips"]]

        def is_completed(c):
            status = (c.get("status") or "").lower()
            return (
                status == "done"
                or status.startswith("store#")
                or status.startswith("delivery#")
            )

        def is_terminated(c):
            return (c.get("status") or "").lower() == "terminate"


        if progress == 0 and all_chips:

            lname = layer_name.lower()

            # --------------------------------------
            # PACKAGE + MEASUREMENT → lifecycle rule
            # --------------------------------------
            if lname in ("package", "measurement"):

                total = 0
                done = 0

                for sub in substeps:
                    chips = sub.get("chips", [])

                    # Exclude entire lifecycle if any terminate
                    if any(is_terminated(c) for c in chips):
                        continue

                    for c in chips:
                        total += 1
                        if is_completed(c):
                            done += 1

                progress = int(100 * done / total) if total else 0

            # --------------------------------------
            # DESIGN + FAB → original logic
            # --------------------------------------
            else:
                done_count = sum(1 for c in all_chips if is_completed(c))
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
            # k = fields["key"]["stringValue"]
            # v = fields["value"]["stringValue"]
            k = firestore_to_python(fields["key"])
            v = firestore_to_python(fields["value"])
            result.append((k, v))
        return result

    # ---- Case B: OLD FORMAT → map of string fields ----
    if mv:
        result = []
        for k, v in mv.items():
            result.append((k, v.get("stringValue", "")))
        return result

    return []


# def list_runs(id_token):
#     url = f"{BASE_URL}/runs"
#     r = requests.get(url, headers={"Authorization": f"Bearer {id_token}"})
#     j = r.json()
#     return j.get("documents", [])

# def list_runs():
#     url = f"{BASE_URL}/runs"
#     r = requests.get(url)  # public read
#     j = r.json()
#     return j.get("documents", [])

def list_runs():
    url = f"{BASE_URL}/runs"
    r = requests.get(url)

    if r.status_code != 200:
        st.error("Failed to fetch runs")
        try:
            st.write(r.json())
        except Exception:
            st.write(r.text)
        return []

    j = r.json()
    return j.get("documents", [])



# def list_runs(id_token):
#     url = f"{BASE_URL}/runs"
#     r = requests.get(
#         url,
#         headers={"Authorization": f"Bearer {id_token}"}
#     )

#     if r.status_code != 200:
#         st.error("Failed to fetch runs.")
#         return []

#     j = r.json()
#     return j.get("documents", [])




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

    # ✅ ADD THIS — timestamp
    if "timestampValue" in v:
        return v["timestampValue"]

    # map
    if "mapValue" in v:
        return {
            kk: firestore_to_python(vv)
            for kk, vv in v["mapValue"].get("fields", {}).items()
        }

    if "nullValue" in v:
        return ""

    return v





def get_meta_value(meta_list, target_key):
    if not meta_list:
        return ""

    for item in meta_list:

        # NEW: tuple-based metadata ("key", "value")
        if isinstance(item, (list, tuple)) and len(item) == 2:
            key, value = item
            if key == target_key:
                return value

        # BACKWARD COMPATIBILITY (old dict style)
        elif isinstance(item, dict):
            if item.get("key") == target_key:
                return item.get("value")

    return ""



def get_meta_data(fields, meta_data_child: str, target_key: str):
    # Load metadata
    meta = fields.get("metadata", {}).get("mapValue", {}).get("fields", {})
    meta_child = meta.get(meta_data_child, {}).get("arrayValue", {}).get("values", [])

    # Convert Firestore objects → Python dict list
    meta_child_py = [firestore_to_python(v) for v in meta_child]

    # Extract value
    return get_meta_value(meta_child_py, target_key)




def substep_chip_html(chip):
    raw_status = chip.get("status", "pending")
    status = (raw_status or "pending").lower()

    chip_name = (chip.get("name") or "").strip()
    chip_type = (chip.get("type") or "").strip().lower()

    # 🔑 special chip detection (robust fallback)
    is_storage  = (chip_type == "storage")  or (chip_name.lower() == "storage")
    is_delivery = (chip_type == "delivery") or (chip_name.lower() == "delivery")

    # ----------------------------------
    # Special display mapping
    # ----------------------------------
    if is_storage:
        if status.startswith("store#"):
            display_label = status          # store#1, store#2, ...
            visual_status = "done"          # reuse green
        else:
            display_label = "storage"
            visual_status = "pending"       # reuse gray

    elif is_delivery:
        if status.startswith("delivery#"):
            display_label = status          # delivery#1, delivery#2, ...
            visual_status = "done"          # reuse green
        else:
            display_label = "delivery"
            visual_status = "pending"       # reuse gray

    else:
        display_label = chip_name
        visual_status = status

    # --- your original colors (UNCHANGED) ---
    # if visual_status == "done":
    #     bg, fg = "#d4edda", "#155724"
    # elif visual_status == "in_progress":
    #     bg, fg = "#fff3cd", "#856404"
    # else:
    #     bg, fg = "#eeeeee", "#555555"

    if visual_status == "done":
        bg, fg = "#d4edda", "#155724"      # green
    elif visual_status == "terminate":
        bg, fg = "#F44336", "#FFFFFF"      # TRUE RED
    elif visual_status == "in_progress":
        bg, fg = "#fff3cd", "#856404"      # yellow
    else:
        bg, fg = "#eeeeee", "#555555"      # gray


    # --- timestamps (may be empty) ---
    started = chip.get("started_at") or ""
    completed = chip.get("completed_at") or ""

    def line(label, value):
        return f"{label} : {value}" if value else f"{label} :"

    tooltip = "&#10;".join([
        html_escape.escape(line("started at", started)),
        html_escape.escape(line("completed at", completed)),
    ])

    name_html = html_escape.escape(display_label)

    return (
        f"<span class='layer-chip' "
        f"style='background:{bg};color:{fg};padding:3px 6px;"
        f"border-radius:4px;font-size:0.78rem;' "
        f"title='{tooltip}'>"
        f"{name_html}"
        f"</span>"
    )




def layer_card_html(layer, idx=None, fridge_labels=None, fields=None, layers=None):


    if idx is not None:
        title_prefix = f"{idx + 1}. "
    else:
        title_prefix = ""

    is_package = layer["layer_name"].lower() == "package"


    progress = int(layer.get("progress", 0))
    substeps = layer["substeps"]

    # detect terminate in this layer
    has_terminate = any(
        (c.get("status") or "").lower() == "terminate"
        for sub in substeps
        for c in sub.get("chips", [])
    )


    # title_html = (
    #     f"{title_prefix}{layer['layer_name']} ({progress}%)"
    #     # f"{fab_progress_bar(progress, 'layer', terminated=has_terminate)}"
    #     f"{fab_progress_bar(progress, 'layer')}"
    # )

    # substeps expanded
    body_html = ""
    is_package = layer["layer_name"].lower() == "package"


    if is_package:
        # -----------------------------
        # Package: 2-column grid layout
        # -----------------------------
        for i in range(0, len(substeps), 2):
            body_html += "<div style='display:flex; gap:14px; margin-top:4px;'>"

            for sub in substeps[i:i+2]:
                # ---- resolve substep label (same logic as before) ----
                if isinstance(sub, str):
                    sub_name = sub
                elif isinstance(sub, dict):
                    label = sub.get("label")
                    name = sub.get("name")

                    if isinstance(label, dict):
                        sub_name = label.get("stringValue")
                    elif isinstance(label, str):
                        sub_name = label
                    elif isinstance(name, dict):
                        sub_name = name.get("stringValue")
                    elif isinstance(name, str):
                        sub_name = name
                    else:
                        sub_name = "Unknown"
                else:
                    sub_name = "Unknown"

                chips_html = " ".join(substep_chip_html(c) for c in sub["chips"])

                body_html += (
                    "<div style='flex:1;'>"
                    f"<div style='font-size:0.80rem; font-weight:600; color:#333;'>{sub_name}</div>"
                    f"<div class='layer-chip-container'>{chips_html}</div>"
                    "</div>"
                )

            body_html += "</div>"

    else:
        # --------------------------------
        # All other layers: original layout
        # --------------------------------
        for sub in substeps:

            # -----------------------------
            # Resolve substep name (UNCHANGED)
            # -----------------------------
            if isinstance(sub, str):
                sub_name = sub

            elif isinstance(sub, dict):
                label = sub.get("label")
                name = sub.get("name")

                if isinstance(label, dict):
                    sub_name = label.get("stringValue")
                elif isinstance(label, str):
                    sub_name = label
                elif isinstance(name, dict):
                    sub_name = name.get("stringValue")
                elif isinstance(name, str):
                    sub_name = name
                else:
                    sub_name = "Unknown"

            else:
                sub_name = "Unknown"


            display_name = sub_name

            # ------------------------------------------------------------
            # Measurement card: show indexed fridge label + chip label
            # (ONLY affects the top card, not the metadata table)
            # ------------------------------------------------------------
            if layer.get("layer_name") == "Measurement" and isinstance(sub, dict):
                fridge_uid = sub.get("fridge_uid")

                # 1) indexed fridge label (Bluefors (1), Bluefors (2), ...)
                if fridge_labels and fridge_uid and fridge_uid in fridge_labels:
                    display_name = fridge_labels[fridge_uid]

                # 2) append chip label (C01, C02, ...) from metadata.measure.fridges[uid].chip_uid
                f = fields or {}
                chip_uid = (
                    f.get("metadata", {})
                     .get("mapValue", {})
                     .get("fields", {})
                     .get("measure", {})
                     .get("mapValue", {})
                     .get("fields", {})
                     .get("fridges", {})
                     .get("mapValue", {})
                     .get("fields", {})
                     .get(fridge_uid, {})
                     .get("mapValue", {})
                     .get("fields", {})
                     .get("chip_uid", {})
                     .get("stringValue")
                )

                pkg_chips = get_package_chips(layers or st.session_state.get("parsed_layers", []))
                chip_label = pkg_chips.get(chip_uid)

                if chip_label:
                    display_name = f"{display_name} ({chip_label})"



            chips_html = " ".join(substep_chip_html(c) for c in sub["chips"])

            hide_substep_label = layer["layer_name"].lower() in ("design", "fabrication", "fab")

            body_html += (
                f"<div style='margin-top:3px;margin-bottom:2px;'>"
                + (
                    ""
                    if hide_substep_label
                    else f"<div style='font-size:0.80rem; font-weight:600; color:#333;'>{display_name}</div>"
                )
                + f"<div class='layer-chip-container'>{chips_html}</div>"
                + "</div>"
            )


    lname = layer["layer_name"].lower()

    # ------------------------------------------
    # PACKAGE + MEASUREMENT → corrected scheme
    # ------------------------------------------
    if lname in ("package", "measurement"):

        if progress == 0:

            total_substeps = len(substeps)
            terminated_substeps = 0

            for sub in substeps:
                chips = sub.get("chips", [])

                # A substep is considered terminated
                # if ANY chip inside is terminated
                if any(
                    (c.get("status") or "").lower() == "terminate"
                    for c in chips
                ):
                    terminated_substeps += 1

            if total_substeps > 0 and terminated_substeps == total_substeps:
                card_class = "layer-card terminated-layer"   # 🔴 all substeps terminated
            else:
                card_class = "layer-card pending-layer"      # ⚪ not all terminated

        elif progress == 100:
            card_class = "layer-card done-layer"

        else:
            card_class = "layer-card progress-layer"

    # ------------------------------------------
    # DESIGN + FAB → original logic untouched
    # ------------------------------------------
    else:
        if has_terminate:
            card_class = "layer-card terminated-layer"
        elif progress == 100:
            card_class = "layer-card done-layer"
        elif progress > 0:
            card_class = "layer-card progress-layer"
        else:
            card_class = "layer-card pending-layer"


    # -------------------------------------------------
    # 🔥 Animation should follow card color semantics
    # -------------------------------------------------
    layer_is_terminated = (card_class == "layer-card terminated-layer")

    title_html = (
        f"{title_prefix}{layer['layer_name']} ({progress}%)"
        f"{fab_progress_bar(progress, 'layer', terminated=layer_is_terminated)}"
    )


    # Final return
    return (
        f"<div class='{card_class}'>"
        f"<div class='layer-card-title'>{title_html}</div>"
        f"{body_html}"
        "</div>"
    )


def fab_progress_bar(pct: int, bar_class: str = "", terminated: bool = False) -> str:
    """
    pct: 0–100
    bar_class: "overall", "layer", "chip" (optional)
    """
    pct = int(pct)

    # Add "fab-progress" + optional size class
    wrapper = f'<div class="fab-progress {bar_class}">'

    # 0% → empty
    if pct <= 0:
        return wrapper + '<div style="width:0%"></div></div>'

    # 100% → completed (static)
    if pct >= 100:
        return wrapper + f'<div class="fab-progress-fill-complete" style="width:{pct}%"></div></div>'

    # # 1–99% → animated stripes
    # return wrapper + f'<div class="fab-progress-fill-flow" style="width:{pct}%"></div></div>'

    # 1–99% → animated unless terminated
    if terminated:
        return wrapper + f'<div class="fab-progress-fill-complete" style="width:{pct}%"></div></div>'
    else:
        return wrapper + f'<div class="fab-progress-fill-flow" style="width:{pct}%"></div></div>'


# -------------------------------------------------------------
# Meta data table ordering
# -------------------------------------------------------------
DESIGN_NORMAL_ORDER = [
    "Creator",
    "Verifier",
    "Lotid",
    "Chip size (mm2)",
    "Spec",
    "File",
    "Notes",
    "Notion",
    "Completed",
]

FAB_NORMAL_ORDER = [
    "Owner",
    "Process",
    # "Lotid",
    "Substrate",
    # "Chip size (mm2)",
    "Qty chips",
    "Fabin",
    "Fabout",
    "Notes",
    "Notion",
]

PACKAGE_NORMAL_ORDER = [
    "PCB PIC*",
    "PCB type",
    "PCB ready",
    "Bond PIC*",
    "Bond date",
    "Bonded chips",
    # "Lotid",
    # "Chip size (mm2)",
    # "Qty chips",
    "Notes",
    # "Dicing date",
    "Notion",
]

MEASURE_NORMAL_ORDER = [
    "Fridge",
    "Owner",
    "Cell type",
    "Chip_id",
    "Cooldown start",
    "Cooldown end",
    "Measure start",
    "Measure end",
    "Warmup start",
    "Warmup end",
    "Notes",
    "Notion",
]

DESIGN_SPECIAL_KEYS = {
    # "Completed",
    # "Notion",
}

FAB_SPECIAL_KEYS = {
    # "Fabin",
    # "Fabout",
    # "Notion",
}

PACKAGE_SPECIAL_KEYS = {
    # "PCB ready",
    # "Dicing date",
    # "Bonding date",
    # "Bonded chips",
    # "Notion",
}

MEASURE_SPECIAL_KEYS = {
    # "Chip_id",
    # "Cooldown start",
    # "Measurement start",
    # "Measurement end",
    # "Warmup start",
    # "Notion",
}


# ------------------------------------------------------------
# PUBLIC VIEWER MODE (No Login)
# ------------------------------------------------------------

# Firestore read is public.
# Viewer does not require authentication.

token = None
email = "public"


def reset_filters():
    st.session_state["lotid_filter"] = ""
    st.session_state["device_filter"] = ""
    st.session_state["fabin_after"] = None
    st.session_state["fabout_before"] = None
    st.rerun()

# ------------------------------------------------------------
# Initialize filter keys in session_state (PREVENT Streamlit API errors)
# ------------------------------------------------------------
for key, default in {
    # "run_filter": "",
    "lotid_filter": "",
    "device_filter": "",
    "fabin_after": None,
    "fabout_before": None
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ------------------------------------------------------------
# Helper: clear all viewer state except login + (optionally) filters
# ------------------------------------------------------------
def clear_viewer_state(keep_filters=True):
    keys_to_keep = {"viewer_user"}  # never delete login

    if keep_filters:
        keys_to_keep.update(
            {"run_filter", "device_filter", "fabin_after", "fabout_before"}
        )

    # Remove everything else from session_state
    for k in list(st.session_state.keys()):
        if k not in keys_to_keep:
            st.session_state.pop(k)



# st.sidebar.write("Logged in as:", email)
# if st.sidebar.button("Logout"):
#     st.session_state.clear()
#     st.rerun()



# ---------------- TOP BAR ----------------
top_left, top_right = st.columns([1.5, 1])

with top_left:
    # redirect_uri = st.secrets["app"]["admin_redirect_uri"]
    # st.link_button("Editor", redirect_uri)

    st.markdown(
        '<div style="text-align: left;">'
        '<a href="https://fab-tracker-7uac3bt2l3sad66hgpvjw6.streamlit.app/" '
        'target="_blank" '
        'style="text-decoration: none; font-weight: 600;">'
        '🔧 Editor'
        '</a>'
        '</div>',
        unsafe_allow_html=True
    )

#     st.markdown(
#         "<h1 style='margin-top: -80px; margin-bottom: -1.2rem;'>🔍 Run Tracker</h1>",
#         unsafe_allow_html=True,
#     )

    # -----------------------------
    # Filter + Run Class (same row)
    # -----------------------------
    fc_left, fc_mid, fc_right = st.columns([2, 0.8, 1.8])


    with fc_left:
        with st.expander("🔍 Filter Runs", expanded=False):
            f_col1, f_col2 = st.columns(2)
            with f_col1:
                lotid_filter = st.text_input(
                    "Lot ID.",
                    "",
                    key="lotid_filter"        # ← minimal change ①
                )
            with f_col2:
                device_filter = st.text_input(
                    "Device name",
                    "",
                    key="device_filter"     # ← minimal change 
                )

            d1, d2 = st.columns(2)
            with d1:
                fabin_after = st.date_input(
                    "Fab-in after",
                    value=None,
                    key="fabin_after"        # ← minimal change ③
                )
            with d2:
                fabout_before = st.date_input(
                    "Fab-out before",
                    value=None,
                    key="fabout_before"      # ← minimal change ④
                )

            c1, c2 = st.columns([1,1])
            with c1:
                apply_btn = st.button("Apply")
            # with c2:
            #     if st.button("Reset Filters"):
            #         st.session_state.reset_filters_triggered = True
            #         st.rerun()
            with c2:
                st.button("Reset", on_click=reset_filters)


    with fc_mid:
        # -----------------------------
        # Run Class View Selector
        # -----------------------------
        run_class_view = st.radio(
            label=" ",
            options=["Main", "Test"],
            index=0,
            horizontal=True,
            key="viewer_run_class",
            label_visibility="collapsed",
        )

    with fc_right:
        if run_class_view == "Main":
            st.success("Electron-on-helium device")
        elif run_class_view == "Test":
            st.success("Non-electron-on-helium device with cooldown")


with top_right:
    st.write("")  # small vertical alignment shift

    # Two columns: refresh button + combined legend
    legend_col, refresh_col = st.columns([0.5, 0.1])

 
    # --- Refresh Button ---
    with refresh_col:
        if st.button("🔄"):
            # st.session_state.refresh_counter += 1
            st.rerun()

     
    with legend_col:
        st.markdown("""
        <div style="
            display:grid;
            grid-template-columns: auto auto;
            column-gap: 24px;
            row-gap: 6px;
            justify-content:end;
        ">

          <!-- completed -->
          <div style="display:flex; align-items:center; gap:4px;">
            <span style="width:10px; height:10px; background:#4caf50;
                         border-radius:50%; display:inline-block;"></span>
            <span style="font-size:1rem;">completed</span>
          </div>

          <!-- in-progress -->
          <div style="display:flex; align-items:center; gap:4px;">
            <span style="width:10px; height:10px; background:#ffd54f;
                         border-radius:50%; display:inline-block;"></span>
            <span style="font-size:1rem;">in-progress</span>
          </div>

          <!-- terminated -->
          <div style="display:flex; align-items:center; gap:4px;">
            <span style="width:10px; height:10px; background:#f44336;
                         border-radius:50%; display:inline-block;"></span>
            <span style="font-size:1rem;">terminated</span>
          </div>

          <!-- pending -->
          <div style="display:flex; align-items:center; gap:4px;">
            <span style="width:10px; height:10px; background:#cccccc;
                         border-radius:50%; display:inline-block;"></span>
            <span style="font-size:1rem;">pending</span>
          </div>

        </div>
        """, unsafe_allow_html=True)


# ------------------------------------------------------------
# Fetch & Display Runs
# ------------------------------------------------------------



# runs = list_runs(token)
runs = list_runs()

if not runs:
    st.info("No runs found.")
    st.stop()



def get_meta_date_for_filter(fields, meta_data_child, target_key):
    # Load metadata
    meta = fields.get("metadata", {}).get("mapValue", {}).get("fields", {})
    meta_child = meta.get(meta_data_child, {}).get("arrayValue", {}).get("values", [])

    # Convert Firestore arrayValue → python
    meta_child_py = [firestore_to_python(v) for v in meta_child]

    # Extract target entry
    return get_meta_value(meta_child_py, target_key)


############ new
# ------------------------------------------------------------
# APPLY FILTER LOGIC
# ------------------------------------------------------------

selected_class = st.session_state.get("viewer_run_class", "Main")

def matches_filters(fields):
    # -------------------------
    # Run Class (ALWAYS applied)
    # -------------------------
    run_class = fields.get("class", {}).get("stringValue", "").strip()
    if run_class != selected_class:
        return False

    # -------------------------
    # Optional filters
    # -------------------------
    run_no = fields["run_no"]["stringValue"]
    device = fields["device_name"]["stringValue"]
    lot_id = get_meta_data(fields, "design", "Lotid")

    fabin_str  = get_meta_date_for_filter(fields, "fab", "Fabin")
    fabout_str = get_meta_date_for_filter(fields, "fab", "Fabout")

    import datetime
    def to_date(s):
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.datetime.strptime(str(s).strip(), fmt).date()
            except ValueError:
                pass
        return None

    fabin_date  = to_date(fabin_str)
    fabout_date = to_date(fabout_str)

    # Optional filters
    # if run_filter and run_filter.lower() not in run_no.lower():
    #     return False
    # if lotid_filter and lotid_filter.lower() not in (lot_id or "").lower():
    #     return False
    if lotid_filter and lotid_filter.strip().lower() != (lot_id or "").strip().lower():
        return False

    if device_filter and device_filter.lower() not in device.lower():
        return False

    if fabin_after:
        if not fabin_date or fabin_date < fabin_after:
            return False

    if fabout_before:
        if not fabout_date or fabout_date > fabout_before:
            return False

    return True



refinement_active = (
    bool(lotid_filter)
    or bool(device_filter)
    or fabin_after is not None
    or fabout_before is not None
)

# if filters_active:
#     filtered_runs = [doc for doc in runs if matches_filters(doc["fields"])]
# else:
#     filtered_runs = runs

filtered_runs = [doc for doc in runs if matches_filters(doc["fields"])]


# # Detect whether any refinemnet filters are active at all
# filters_active = (
#     apply_btn
#     or bool(run_filter)
#     or bool(device_filter)
#     or fabin_after is not None
#     or fabout_before is not None
# )




# --- Sort runs by run_no descending (e.g. 003 > 002 > 001) ---
filtered_runs.sort(key=lambda d: d["fields"]["run_no"]["stringValue"], reverse=True)


for doc in filtered_runs:
    # fields = doc["fields"]
    fields = copy.deepcopy(doc["fields"])
    run_no = fields["run_no"]["stringValue"]
    device = fields["device_name"]["stringValue"]
    created_date = fields["created_date"]["stringValue"]
    creator = fields["creator"]["stringValue"]

    cooldown_triggered = False

    layers = parse_layers(fields)
    # st.write("DEBUG PARSED LAYERS:", layers)   # ← ADD HERE


    # ------------------------------------------------------------
    # Measurement fridge labels (SOURCE OF TRUTH: Flow editor)
    # Matches Flow editor numbering: Bluefors (1), Bluefors (2), ...
    # ------------------------------------------------------------
    raw_fridges = get_measure_fridges(layers)

    def make_unique_label(base, existing_labels, force_index=False):
        if not force_index and base not in existing_labels:
            return base
        i = 1
        while f"{base} ({i})" in existing_labels:
            i += 1
        return f"{base} ({i})"

    # count base labels
    base_counts = {}
    for base in raw_fridges.values():
        base_counts[base] = base_counts.get(base, 0) + 1

    fridge_labels = {}
    used_labels = []

    for uid, base_label in raw_fridges.items():
        force_index = base_counts.get(base_label, 0) > 1
        final_label = make_unique_label(base_label, used_labels, force_index)
        fridge_labels[uid] = final_label
        used_labels.append(final_label)


    # -------------------------------------------------
    # Measurement table labels (indexed, NO chip)
    # -------------------------------------------------
    fridge_labels_no_chip = {}
    used_labels = []

    for uid, base_label in raw_fridges.items():
        force_index = base_counts.get(base_label, 0) > 1
        final_label = make_unique_label(base_label, used_labels, force_index)
        fridge_labels_no_chip[uid] = final_label
        used_labels.append(final_label)

    ############ old
    # def should_show_layer(layers, idx):
    #     layer = layers[idx]
    #     layer_name = (layer.get("layer_name") or "").lower()

    #     # Design is always visible
    #     if idx == 0:
    #         return True

    #     # 🔑 Measurement visibility latch
    #     if layer_name == "measurement":
    #         if measurement_has_started(layers, fields):
    #             return True

    #     # Default strict gating (unchanged)
    #     for j in range(idx):
    #         if int(layers[j].get("progress", 0)) < 100:
    #             return False

    #     return True

    def should_show_layer(layers, idx):
        # 🔓 If any measurement cooldown has started → show ALL layers
        if measurement_has_started(layers, fields):
            return True

        # Design always visible
        if idx == 0:
            return True

        # Strict gating before cooldown
        for j in range(idx):
            if int(layers[j].get("progress", 0)) < 100:
                return False

        return True



    # ---------------------------------------------------
    # DETERMINE WHICH LAYERS ARE ACTUALLY VISIBLE
    # ---------------------------------------------------
    visible_layers = []
    for idx, layer in enumerate(layers):
        if should_show_layer(layers, idx):
            visible_layers.append(layer)


    # ---------------------------------------
    # Collapse ONLY when all 4 main layers are done
    # ---------------------------------------

    def find_layer(layers, name):
        for l in layers:
            if l["layer_name"].lower() == name.lower():
                return l
        return None

    # Grab layers
    design_layer = find_layer(layers, "Design")
    fab_layer = find_layer(layers, "Fabrication")
    pkg_layer = find_layer(layers, "Package")
    measure_layer = find_layer(layers, "Measurement")   

    def done(layer):
        return layer and int(layer.get("progress", 0)) == 100

    # Collapse only when ALL four layers are completed
    pipeline_all_done = (
        done(design_layer)
        and done(fab_layer)
        and done(pkg_layer)
        and done(measure_layer)
    )

    auto_expand = not pipeline_all_done




    # ---------------------------------------------------
    # 🔍 CHECK COOLDOWN CHIP STATUS (PUT THIS HERE)
    # ---------------------------------------------------
    for layer in layers:
        if layer["layer_name"].lower() == "measurement":
            for sub in layer["substeps"]:
                for chip in sub["chips"]:
                    # st.write("DEBUG CHIP:", chip)

                    # if chip["name"].lower() == "cooldown":
                    if "cool" in chip["name"].lower():
                        status = chip["status"]
                        if status in ("in_progress", "done"):
                            cooldown_triggered = True
    # ----------------------------------------------------
 


    def is_completed(c):
        status = (c.get("status") or "").lower()
        return (
            status == "done"
            or status.startswith("store#")
            or status.startswith("delivery#")
        )

    def is_terminated(c):
        return (c.get("status") or "").lower() == "terminate"

    # total = 0
    # done = 0

    # for l in layers:
    #     for s in l.get("substeps", []):
    #         for c in s.get("chips", []):

    #             # Ignore terminated chips entirely
    #             if is_terminated(c):
    #                 continue

    #             total += 1

    #             if is_completed(c):
    #                 done += 1

    # overall = done / total if total else 0

    total = 0
    done = 0

    for l in layers:
        lname = (l.get("layer_name") or "").lower()

        for s in l.get("substeps", []):
            chips = s.get("chips", [])

            # ------------------------------------------
            # Match parse_layers lifecycle rule
            # ------------------------------------------
            if lname in ("package", "measurement"):
                # If any chip in substep is terminated,
                # exclude entire substep
                if any(
                    (c.get("status") or "").lower() == "terminate"
                    for c in chips
                ):
                    continue

            for c in chips:
                status = (c.get("status") or "").lower()

                total += 1

                if (
                    status == "done"
                    or status.startswith("store#")
                    or status.startswith("delivery#")
                ):
                    done += 1

    overall = done / total if total else 0



    layers_html = ""
    for idx, layer in enumerate(layers):

        # ⭐ NEW: Only show unlocked layers
        if not should_show_layer(layers, idx):
            continue

        layers_html += "<div class='step-block'>"
        layers_html += layer_card_html(layer, idx, fridge_labels, fields=fields, layers=layers)

        # Show arrow only if the *next* layer is also visible
        if idx < len(layers) - 1 and should_show_layer(layers, idx + 1):
            layers_html += "<div class='arrow-cell'>➜</div>"

        layers_html += "</div>"



    design_date = get_meta_data(fields,"design", "Completed")
    fab_in = format_date_compact(get_meta_data(fields,"fab", "Fabin"))
    fab_out = format_date_compact(get_meta_data(fields,"fab", "Fabout"))
    lot_id = get_meta_data(fields,"design", "Lotid")
    # bond_date = get_meta_data(fields,"package", "Bond date")
    # cooldown_date = get_meta_data(fields,"measure", "Cooldown start")

    # ---- Measurement meta for banner (fridge-centric) ----

    fridge_labels = get_measure_fridges(layers)

    meta_fields = (
        fields.get("metadata", {})
            .get("mapValue", {})
            .get("fields", {})
    )

    meas_meta = (
        meta_fields.get("measure", {})
            .get("mapValue", {})
            .get("fields", {})
            .get("fridges", {})
            .get("mapValue", {})
            .get("fields", {})
    )


    fridge_display_label = build_measurement_fridge_display_labels(layers)

    cooldown_texts = []

    for fridge_uid, fridge_label in fridge_display_label.items():
        f = firestore_to_python(meas_meta.get(fridge_uid, {})) if meas_meta else {}
        cd = f.get("cooldown_start", "")
        if cd:
            cooldown_texts.append(
                f"{fridge_label} {format_date_compact(cd)}"
            )

    cooldown_banner_text = ", ".join(cooldown_texts)



    # detect terminate anywhere in run (for overall progress bar)
    has_terminate_global = any(
        (c.get("status") or "").lower() == "terminate"
        for l in layers
        for s in l.get("substeps", [])
        for c in s.get("chips", [])
    )


    dashboard_events = collect_dashboard_events_from_metadata(
        fields=fields,
        layers=layers,
    )

    dashboard_text = ""

    if dashboard_events:
        # 1️⃣ Find highest-priority event group (lowest number wins)
        best_priority = min(e["priority"] for e in dashboard_events)

        best_events = [
            e for e in dashboard_events
            if e["priority"] == best_priority
        ]

        # Most recent among highest-priority events
        primary = max(best_events, key=lambda e: e["timestamp"])

        # 2️⃣ Check for newer lower-priority events
        newer_lower = [
            e for e in dashboard_events
            if e["priority"] > best_priority and e["timestamp"] > primary["timestamp"]
        ]

        if newer_lower:
            secondary = max(newer_lower, key=lambda e: e["timestamp"])
            dashboard_text = f"{secondary['message']}  ||  {primary['message']}"
            # st.info(combined_msg)
        else:
            # st.info(primary["message"])
            dashboard_text = primary["message"]

    # -------------------------------------------------
    # Overall termination follows layer color semantics
    # -------------------------------------------------
    has_terminated_layer = False

    for l in layers:
        lname = (l.get("layer_name") or "").lower()
        progress_l = int(l.get("progress", 0))
        substeps_l = l.get("substeps", [])

        # PACKAGE + MEASUREMENT
        if lname in ("package", "measurement"):

            total = len(substeps_l)
            terminated = 0

            for sub in substeps_l:
                chips = sub.get("chips", [])
                if any((c.get("status") or "").lower() == "terminate" for c in chips):
                    terminated += 1

            if total > 0 and terminated == total:
                has_terminated_layer = True
                break

        # DESIGN + FAB
        else:
            if any(
                (c.get("status") or "").lower() == "terminate"
                for s in substeps_l
                for c in s.get("chips", [])
            ):
                has_terminated_layer = True
                break


    html = (
        "<div>"
        # f"<h4 style='margin:0 0 4px 0;'>Run: {run_no}</h4>"

        # ---------------- METADATA + RIGHT-ALIGNED BAR ----------------
        "<div style='display:flex; align-items:center; justify-content:space-between; width:80%;'>"

            # LEFT SIDE: metadata fields
            "<div style='font-size:0.9rem; white-space:nowrap;'>"
          
            "</div>"

            "<div style='display:flex; align-items:center; justify-content:space-between; width:100%;'>"

                # progress block
                "<div style='display:flex; align-items:center; gap:8px; flex:0 0 80%;'>"
                    f"<div style='font-size:0.9rem; font-weight:600; white-space:nowrap;'>Overall progress ({int(round(overall*100))}%)</div>"
                    f"{fab_progress_bar(int(overall*100), 'overall', terminated=has_terminated_layer)}"
                "</div>"

                # spacer (pushes dashboard to far right)
                "<div style='flex:1;'></div>"

                # dashboard text
                # "<div style='font-size:0.9rem; color:#1f3b63; white-space:nowrap;'>"
                "<div style='font-size:0.9rem; color:var(--text-color); white-space:nowrap;'>"
                    f"{dashboard_text}"
                "</div>"

            "</div>"


        "</div>"

        "<div style='width:100%; height:4px; background: var(--secondary-background-color); margin: 6px 0px 8px;'></div>"

        "<div class='layer-grid'>"
        f"{layers_html}"
        "</div>"
        "</div>"
    )



    # ---------------------------------------
    # All layers are done, run card collapse
    # ---------------------------------------

    # A layer is done if progress == 100
    def done(layer):
        return int(layer.get("progress", 0)) == 100

    # Collapse only when *every* layer is 100%
    all_done = all(done(layer) for layer in visible_layers)

    auto_expand = not all_done



    # If refinement filters applied → always expand
    if refinement_active:
        auto_expand = True


    # ----------------------------
    # EXPANDER FOR THIS RUN
    # ----------------------------

    # Visible label (what user sees)
    visible_label = (
        # f"#️ {run_no} ㅤ ⌨ {device} ㅤ 🆔 {lot_id} ㅤ ⚒️ fab {date_only(fab_in)} ➔ {date_only(fab_out)} ㅤ ❄️ Cooldown Start : {cooldown_banner_text}"
        f"#️ {run_no}  🆔 {lot_id} ㅤ ⌨ {device} ㅤ ⚒️ Fab {date_only(fab_in)} ➔ {date_only(fab_out)}"

    )

    with st.expander(visible_label, expanded=auto_expand):

        # ---------------------------------------------------

        # run card UI
        # st.markdown("<div class='run-card'>" + html + "</div>", unsafe_allow_html=True)
        st.markdown(html, unsafe_allow_html=True)

        # -------- Metadata tables -------
        meta = fields.get("metadata", {}).get("mapValue", {}).get("fields", {})
        design_meta  = parse_metadata_section(meta.get("design", {}))
        fab_meta     = parse_metadata_section(meta.get("fab", {}))
        # package_meta = parse_metadata_section(meta.get("package", {}))
        # measure_meta = parse_metadata_section(meta.get("measure", {}))

        # ------------------------------
        # Package metadata (chip-centric)
        # ------------------------------
        pkg_meta = (
            meta.get("package", {})
                .get("mapValue", {})
                .get("fields", {})
                .get("chips", {})
                .get("mapValue", {})
                .get("fields", {})
        )

        package_meta = {
            uid: firestore_to_python(v)
            for uid, v in pkg_meta.items()
        }


        # ------------------------------
        # Measurement metadata (fridge-centric)
        # ------------------------------
        meas_meta = (
            meta.get("measure", {})
                .get("mapValue", {})
                .get("fields", {})
                .get("fridges", {})
                .get("mapValue", {})
                .get("fields", {})
        )

        measure_meta_clean = {
            uid: firestore_to_python(v)
            for uid, v in meas_meta.items()
        }



        # ✅ Tabs instead of expanders
        tab_design, tab_fab, tab_pkg, tab_meas = st.tabs(
            ["Design", "Fab", "Package", "Measure"]
        )

        with tab_design:
    
            row_raw = design_meta_to_row(design_meta)

            design_order = [
                "Creator",
                "Verifier",
                "Lotid",
                "Chip size (mm2)",
                "Notion",
                "Spec",
                "Notes",
                "File",
                "Completed",
            ]

            row = {k: row_raw.get(k, "") for k in design_order if k in row_raw}

            # st.dataframe(
            #     [row],
            #     hide_index=True,
            #     use_container_width=True,
            #     column_config={
            #         "File": st.column_config.LinkColumn(
            #             "File (chip)", display_text=r".*#(.*)"
            #         ),
            #     },
            # )
            col_cfg = {
                "File": st.column_config.LinkColumn(
                    "File (chip)", display_text=r".*#(.*)"
                ),
            }

            if row.get("Notion"):
                notion_url = row.get("Notion")

                display_text = notion_url

                if isinstance(notion_url, str) and "/" in notion_url:
                    # Get last path segment
                    slug = notion_url.rstrip("/").split("/")[-1]

                    # Remove trailing 32-char page ID
                    if "-" in slug:
                        slug = slug.rsplit("-", 1)[0]

                    # Replace hyphens with spaces
                    display_text = slug.replace("-", " ")

                col_cfg["Notion"] = st.column_config.LinkColumn(
                    "Notion",
                    display_text=display_text,
                )

            st.dataframe(
                [row],
                hide_index=True,
                use_container_width=True,
                column_config=col_cfg,
            )

#
        with tab_fab:
            row_raw = design_meta_to_row(fab_meta)

            row = {
                k: v
                for k, v in row_raw.items()
                if not (
                    (k or "").strip().lower() in ("lotid", "lot id", "lotid ")
                    or k == "File"
                    or k.startswith("FileId_")
                    or k.startswith("FileName_")
                    or k in ("Fab Top Callout", "Fab Child Page IDs")
                )
            }

            col_cfg = {}
            if row.get("Notion"):
                # ✅ Option A: Lot ID comes from DESIGN metadata (single source of truth)
                design_row = design_meta_to_row(design_meta)

                lot_id = (
                    design_row.get("Lotid")
                    or design_row.get("Lot ID")
                    or design_row.get("LotID")
                    or ""
                )

                col_cfg["Notion"] = st.column_config.LinkColumn(
                    "Notion",
                    display_text=lot_id if lot_id else "Link",
                )

            st.dataframe(
                [row],
                hide_index=True,
                use_container_width=True,
                column_config=col_cfg if col_cfg else None,
            )



            # ✅ Always show all attachments under the table
            files = extract_fab_attachments(fab_meta)

            # st.markdown("Wafer design")
            if not files:
                st.caption("No attachments")
            # else:
            #     for f in files:
            #         fid = f.get("id", "")
            #         name = f.get("name", "") or fid
            #         if fid:
            #             st.markdown(f"- [{name}]({drive_download_url(fid)})")
            else:
                links = []
                for f in files:
                    fid = f.get("id", "")
                    name = f.get("name", "") or fid
                    if fid:
                        url = drive_download_url(fid)
                        links.append(f"[{name}]({url})")

                if links:
                    final_links = (" , ".join(links))
                    # st.markdown(" | ".join(links))
                    st.write(f"Design file : {final_links}")


        with tab_pkg:

            chip_labels = get_package_chips(layers)

            if not chip_labels:
                st.info("No package chips defined.")
            else:
                # rows = render_package_table_clean(package_meta, chip_labels)
                rows = render_package_table_clean(package_meta, chip_labels, layers)

                st.dataframe(
                    rows,
                    hide_index=True,
                    use_container_width=True,
                )


        with tab_meas:

            used_labels = []

            for uid, base_label in raw_fridges.items():
                force_index = base_counts.get(base_label, 0) > 1
                final_label = make_unique_label(base_label, used_labels, force_index)

                # -------------------------------------------------
                # Measurement: append chip label HERE (source of truth)
                # -------------------------------------------------
                meta_f = measure_meta_clean.get(uid, {})
                chip_uid = meta_f.get("chip_uid")

                if chip_uid:
                    chip_label = get_package_chips(layers).get(chip_uid)
                    if chip_label:
                        final_label = f"{final_label} ({chip_label})"

                fridge_labels[uid] = final_label
                used_labels.append(final_label)


            package_chips = get_package_chips(layers)


            if not fridge_labels:
                st.info("No fridges defined in Measurement flow.")
            else:
                rows = []

                for fridge_uid, fridge_label in fridge_labels.items():
                    meta_f = measure_meta_clean.get(fridge_uid, {})
                    # meta_f = measure_meta_clean.get("fridges", {}).get(fridge_uid, {})

                    chip_uid = meta_f.get("chip_uid")

                    # -----------------------------------
                    # Termination override (Option A - viewer only)
                    # -----------------------------------
                    cooldown_display = format_range_compact(
                        meta_f.get("cooldown_start", ""),
                        meta_f.get("cooldown_end", ""),
                    )

                    measure_display = format_range_compact(
                        meta_f.get("measure_start", ""),
                        meta_f.get("measure_end", ""),
                    )

                    warmup_display = format_range_compact(
                        meta_f.get("warmup_start", ""),
                        meta_f.get("warmup_end", ""),
                    )

                    storage_display = format_date_compact(
                        meta_f.get("storage_time", "")
                    )

                    for layer in layers:
                        if (layer.get("layer_name") or "").lower() != "measurement":
                            continue

                        for sub in layer.get("substeps", []):
                            if sub.get("fridge_uid") != fridge_uid:
                                continue

                            for chip in sub.get("chips", []):
                                name = (chip.get("name") or "").lower()
                                status = (chip.get("status") or "").lower()

                                if status != "terminate":
                                    continue

                                if "cool" in name:
                                    cooldown_display = "terminated"

                                elif "measure" in name:
                                    measure_display = "terminated"

                                elif "warm" in name:
                                    warmup_display = "terminated"

                                elif "store" in name:
                                    storage_display = "terminated"


                    rows.append({
                        "Fridge": fridge_labels_no_chip.get(fridge_uid, ""),
                        "Owner": meta_f.get("owner", ""),
                        "Chip": (
                            package_chips.get(chip_uid, "")
                            if chip_uid
                            else ""
                        ),

                        "Cell type": meta_f.get("cell_type", ""),
                        "Cooldown": cooldown_display,
                        "Measure": measure_display,
                        "Warmup": warmup_display,

                        # ✅ NEW (minimal)
                        "Storage": meta_f.get("storage", ""),  # e.g. store#1
                        # "Storage date": format_date_compact(meta_f.get("storage_time", "")),   
                        "Storage date": storage_display,
               
                        # 👇 ADD THIS LINE (viewer-only, hidden later)
                        "_cooldown_start": meta_f.get("cooldown_start", ""),

                        "Notion": meta_f.get("notion", ""),
                        "Notes": meta_f.get("notes", ""),
                    })





            # ------------------------------------------------------------
            # Measurement table (clickable Notion link)
            # ------------------------------------------------------------

            # for r in rows:
            #     url = (r.get("Notion") or "").strip()
            #     if url:
            #         label = _meas_notion_label(
            #             r.get("Fridge", ""),
            #             r.get("_cooldown_start", ""),
            #         )
            #         r["Notion"] = f"{url}# {label}"

            #     # remove helper before display
            #     r.pop("_cooldown_start", None)

            NOTION_DB_MAP = {
                "Bluefors": st.secrets["notion"]["NOTION_MEAS_DB_URL_BLUEFORS"],
                "ICEOxford": st.secrets["notion"]["NOTION_MEAS_DB_URL_ICEOXFORD"],
            }

            # ------------------------------------------------------------
            # Measurement table (clickable Fridge + clickable Notion label)
            # ------------------------------------------------------------

            for r in rows:
                # 1) Fridge column → link to the right Measurement DB
                fridge_label = (r.get("Fridge") or "").strip()
                db_url = NOTION_DB_MAP.get(fridge_label)
                if db_url:
                    r["Fridge"] = f"{db_url}# {fridge_label}"

                # 2) Notion column → keep your previous working behavior
                url = (r.get("Notion") or "").strip()
                if url:
                    label = _meas_notion_label(
                        fridge_label,                 # IMPORTANT: use original label text
                        r.get("_cooldown_start", ""),
                    )
                    r["Notion"] = f"{url}# {label}"

                # remove helper before display
                r.pop("_cooldown_start", None)

            st.dataframe(
                rows,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Fridge": st.column_config.LinkColumn(
                        "Fridge",
                        display_text=r".*#(.*)",
                    ),
                    "Notion": st.column_config.LinkColumn(
                        "Notion",
                        display_text=r".*#(.*)",
                    ),
                },
            )
