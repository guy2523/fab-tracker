
import streamlit as st
from core.metadata import (normalize_meta, ensure_kv_rows, build_package_chip_meta, get_package_chips, get_measure_fridges)
from firebase_client import firestore_set, firestore_update_field, firestore_get, firestore_to_python
import copy
import datetime
import os
import subprocess
import sys, json
from zoneinfo import ZoneInfo
from datetime import datetime


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


def _pick_meas_db_url(fridge_label: str) -> str:
    lab = (fridge_label or "").strip().lower()
    notion_sec = st.secrets.get("notion", {})

    if "ice" in lab:       # "ICEOxford"
        return (notion_sec.get("NOTION_MEAS_DB_URL_ICEOXFORD") or "").strip()
    if "blue" in lab:      # "Bluefors"
        return (notion_sec.get("NOTION_MEAS_DB_URL_BLUEFORS") or "").strip()
    return ""


def run_notion_subprocess(*, script_path: str, payload: dict) -> dict:
    env = os.environ.copy()
    env["NOTION_TOKEN"] = st.secrets["notion"]["NOTION_TOKEN"]
    env["NOTION_FAB_DB_URL"] = st.secrets["notion"]["NOTION_FAB_DB_URL"]
    env["NOTION_MEAS_DB_URL_ICEOXFORD"] = st.secrets["notion"]["NOTION_MEAS_DB_URL_ICEOXFORD"]
    env["NOTION_MEAS_DB_URL_BLUEFORS"]  = st.secrets["notion"]["NOTION_MEAS_DB_URL_BLUEFORS"]
   
    p = subprocess.run(
        [sys.executable, script_path, json.dumps(payload)],
        capture_output=True,
        text=True,
        env=env,
    )

    stdout = (p.stdout or "").strip()
    stderr = (p.stderr or "").strip()

    if p.returncode != 0:
        # show both; stdout might contain JSON error
        raise RuntimeError(stderr or stdout or f"Notion script failed (code={p.returncode})")

    try:
        return json.loads(stdout)
    except Exception:
        raise RuntimeError(f"Notion script returned non-JSON output: {stdout[:200]}")


def format_range(start, end):
    if start and end:
        return f"{start} – {end}"
    if start:
        return f"{start} –"
    if end:
        return f"– {end}"
    return ""


def format_date_compact(v: str) -> str:
    if not v:
        return ""
    try:
        # expects "YYYY-MM-DD ..." (like your Firestore strings)
        y, m, d = v.split(" ")[0].split("-")
        return f"{y[2:]}/{m}/{d}"
    except Exception:
        return v


def build_fridge_display_map(meas_fridges, flow_substeps):
    """
    meas_fridges: {fridge_uid: label}
    flow_substeps: measurement layer substeps IN FLOW ORDER
    returns: {fridge_uid: display_name}
    """
    from collections import defaultdict

    # Preserve flow order
    ordered = []
    for sub in flow_substeps:
        if not isinstance(sub, dict):
            continue
        uid = sub.get("fridge_uid")
        label = sub.get("label")
        if uid and label:
            ordered.append((uid, label))

    # Group by label in flow order
    by_label = defaultdict(list)
    for uid, label in ordered:
        by_label[label].append(uid)

    display = {}

    for label, uids in by_label.items():
        if len(uids) == 1:
            display[uids[0]] = label
        else:
            for i, uid in enumerate(uids, start=1):   # 👈 NO SORT
                display[uid] = f"{label} ({i})"

    return display



def edit_metadata(title, meta_list, n_cols=3, skip_normalize=False, disable_keys=(), hide_keys=(), render_footer=None):
    run_suffix = st.session_state.get("loaded_run_no", "NA")

    auto_keys = set(k.lower() for k in disable_keys)
    hide_set  = set(k.lower() for k in hide_keys)   # ✅ NEW

    def _is_hidden(k: str) -> bool:
        kl = (k or "").strip().lower()
        if kl in hide_set:
            return True
        # ✅ prefix-hide support: "fileid_" hides "fileid_1", "fileid_2", ...
        for hk in hide_set:
            if hk.endswith("_") and kl.startswith(hk):
                return True
        return False



    if not skip_normalize:
        meta_list = normalize_meta(meta_list)

    # with st.expander(title, expanded=False):

    # Categorize fields
    single_line = []
    multi_line = []
    # new_list = []
    new_list = [dict(x) for x in meta_list]

    for idx, item in enumerate(meta_list):
        key = item["key"].strip()
        if not key:
            continue

        # k_l = key.lower()
        # if k_l in hide_set:
        #     # new_list.append(item)
        #     continue

        if _is_hidden(key):
            continue


        val = item["value"]

        # Notes should also be multiline (inside columns)
        # if key.lower() == "notes":
        if key.lower() in ("notes", "spec"):
            multi_line.append({"item": item, "idx": idx})
            continue

        # Detect multiline fields
        if isinstance(val, str) and "\n" in val:
            multi_line.append({"item": item, "idx": idx})
        else:
            single_line.append({"item": item, "idx": idx})

    # new_list = []
    # new_list = [dict(x) for x in meta_list]   # ✅ start as a copy, preserving hidden rows

    # -----------------------------------------
    # 1️⃣ SINGLE-LINE FIELDS (3 columns)
    # -----------------------------------------
    if single_line:
        cols = st.columns(n_cols)
        for i, entry in enumerate(single_line):
            item = entry["item"]
            idx = entry["idx"]
            key = item["key"]
            val = item["value"]

            with cols[i % n_cols]:
                widget_key = f"{title}_{run_suffix}_{key}_{idx}"
                k_l = key.strip().lower()
                disp_val = val

                # # ✅ match viewer display for disabled Fabin/Fabout
                # if k_l in ("fabin", "fabout") and (k_l in auto_keys):
                #     disp_val = format_date_compact(val)

                # # ✅ ADD HERE
                # if k_l in disable_keys:
                #     if st.session_state.get(widget_key) != disp_val:
                #         st.session_state[widget_key] = disp_val

                # ✅ UI-only: refresh disabled widgets so they show latest value after overrides
                if k_l in auto_keys:
                    if st.session_state.get(widget_key) != disp_val:
                        st.session_state[widget_key] = disp_val

                new_val = st.text_input(
                    key,
                    disp_val,
                    key=widget_key,
                    disabled=(k_l in disable_keys)
                )


            # if key.strip().lower() in auto_keys:
            #     # 🔒 preserve disabled keys exactly as-is
            #     new_list.append({"key": key, "value": val})
            # else:
            #     new_list.append({"key": key, "value": new_val})


            # ✅ write back in place (preserves original meta_list ordering)
            if key.strip().lower() in auto_keys:
                new_list[idx]["value"] = val       # keep disabled exactly
            else:
                new_list[idx]["value"] = new_val



    # -----------------------------------------
    # 2️⃣ MULTILINE FIELDS (including NOTES)
    # -----------------------------------------
    if multi_line:
        cols = st.columns(3)
        for i, entry in enumerate(multi_line):
            item = entry["item"]
            idx = entry["idx"]
            key = item["key"]
            val = item["value"]

            widget_key = f"{title}_{run_suffix}_{key}_{idx}"

            # ✅ Notes: full width (no columns)
            if key.strip().lower() in ("notes", "spec"):
                new_val = st.text_area(
                    key,
                    val,
                    key=widget_key,
                    height=120,   # optional: taller too
                )
            else:
                with cols[i % 3]:
                    new_val = st.text_area(
                        key,
                        val,
                        key=widget_key,
                        height=120,
                    )

            # if key.strip().lower() in auto_keys:
            #     new_list.append({"key": key, "value": item["value"]})
            # else:
            #     new_list.append({"key": key, "value": new_val})

            if key.strip().lower() in auto_keys:
                new_list[idx]["value"] = val
            else:
                new_list[idx]["value"] = new_val



    # ---------------------------------
    # Optional footer (overrides etc.)
    # ---------------------------------
    if render_footer:
        # st.markdown("---")
        render_footer()


    # 🔑 SINGLE SOURCE OF TRUTH
    section_key = title.split()[-1].lower()
    # st.session_state["update_meta"][section_key] = new_list
    if section_key != "measurement":
        st.session_state["update_meta"][section_key] = new_list


    return new_list



########################################################
########################################################


def render_design_override(*, loaded_run_no, loaded_run_doc_id, fields, layers_py, update_meta, save_full_run, id_token,):

    save_col, override_col = st.columns([1, 2])


    with save_col:
        if False:
            if st.button(
                "💾 Save Design Info",
                key=f"save_design_meta_{loaded_run_no}",
            ):
                save_full_run()          # ✅ ONLY THIS
                st.success("Design metadata saved")
                st.rerun()


    # -------------------------------
    # 🔁 Override Design Completed
    # -------------------------------
    with override_col:
        completed_row = next(
            (r for r in update_meta["design"]
             if r["key"].strip().lower() == "completed"),
            None
        )

        if completed_row:

            cb_key = f"ovr_design_completed_{loaded_run_doc_id}"
            pending_key = f"__pending_uncheck_{cb_key}"

            # ✅ apply deferred uncheck BEFORE the checkbox widget is created
            if st.session_state.get(pending_key, False):
                st.session_state[cb_key] = False
                st.session_state[pending_key] = False

            if st.checkbox(
                "Override Completed time",
                key=cb_key,
            ):

                default_val = (
                    completed_row["value"]
                    if completed_row["value"]
                    else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )

                new_val = st.text_input(
                    "Date (YYYY-MM-DD HH:MM:SS)",
                    value=default_val,
                    key=f"dc_text_{loaded_run_doc_id}",
                )

                if st.button(
                    # "Apply Design Completed",
                    "Apply",
                    key=f"apply_design_completed_{loaded_run_doc_id}",
                ):
                    try:
                        datetime.fromisoformat(new_val)

                        completed_row["value"] = new_val
                        st.session_state["design_completed_overridden"] = True

                        firestore_set(
                            "runs",
                            loaded_run_doc_id,
                            {
                                "run_no": fields["run_no"]["stringValue"],
                                "device_name": fields["device_name"]["stringValue"],
                                "created_date": fields["created_date"]["stringValue"],
                                "creator": fields["creator"]["stringValue"],
                                "steps": layers_py,
                                "metadata": update_meta,
                            },
                            id_token=id_token,
                        )

                        st.success("Design Completed updated")

                        # ✅ one-shot override: re-enable progress-driven clear/set logic
                        # st.session_state[f"ovr_design_completed_{loaded_run_no}"] = False
                        st.session_state[pending_key] = True

                        st.rerun()

                    except ValueError:
                        st.error("Invalid datetime format. Use YYYY-MM-DD HH:MM:SS")


########################################################
########################################################


def render_fab_override(*, loaded_run_no, loaded_run_doc_id, fields, layers_py, update_meta, save_full_run, id_token,):

    save_col, override_col = st.columns([1, 2])

    # -------------------------------
    # 💾 Normal Save (DOES NOT TOUCH TIMES)
    # -------------------------------
    with save_col:
        if False:
            if st.button(
                "💾 Save Fab Info",
                key=f"save_fab_meta_{loaded_run_no}",
            ):
                save_full_run()      # ✅ ONLY THIS
                st.success("Fab metadata saved")
                st.rerun()

    # -------------------------------
    # 🔁 Override FAB timestamps (FABIN / FABOUT same row)
    # -------------------------------
    with override_col:
        col_fabin, col_fabout = st.columns(2)

        def render_one(key: str, col):
            with col:
                row = next(
                    (r for r in update_meta["fab"]
                     if (r.get("key") or "").strip().lower() == key),
                    None
                )
                if not row:
                    return

                cb_key = f"ovr_fab_{key}_{loaded_run_doc_id}"
                pending_key = f"__pending_uncheck_{cb_key}"

                # ✅ apply deferred uncheck BEFORE the checkbox widget is created
                if st.session_state.get(pending_key, False):
                    st.session_state[cb_key] = False
                    st.session_state[pending_key] = False

                # if st.checkbox(
                #     f"Override {key.upper()} time",
                #     key=f"ovr_fab_{key}_{loaded_run_no}",
                # ):

                if st.checkbox(
                    f"Override {key.upper()} time",
                    key=cb_key,
                ):


                    default_val = (
                        row.get("value")
                        if row.get("value")
                        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )

                    new_val = st.text_input(
                        "Date (YYYY-MM-DD HH:MM:SS)",
                        value=default_val,
                        key=f"text_fab_{key}_{loaded_run_doc_id}",
                    )

                    if st.button(
                        "Apply",
                        key=f"apply_fab_{key}_{loaded_run_doc_id}",
                    ):
                        try:
                            datetime.fromisoformat(new_val)

                            row["value"] = new_val

                            firestore_set(
                                "runs",
                                loaded_run_doc_id,
                                {
                                    "run_no": fields["run_no"]["stringValue"],
                                    "device_name": fields["device_name"]["stringValue"],
                                    "created_date": fields["created_date"]["stringValue"],
                                    "creator": fields["creator"]["stringValue"],
                                    "steps": layers_py,
                                    "metadata": update_meta,
                                },
                                id_token=id_token,
                            )

                            st.success(f"{key.upper()} updated")

                            # ✅ one-shot override: re-enable progress-driven clear/set logic
                            # st.session_state[f"ovr_design_completed_{loaded_run_no}"] = False
                            st.session_state[pending_key] = True

                            st.rerun()

                        except ValueError:
                            st.error("Invalid datetime format. Use YYYY-MM-DD HH:MM:SS")

        render_one("fabin", col_fabin)
        render_one("fabout", col_fabout)


########################################################
########################################################

def save_package_info_core(
    *,
    chip_uid,
    chip_meta_live,
    fields,
    update_layers,
    update_meta,
    loaded_run_doc_id,
    id_token,
):
    updated = {
        "pcb_pic":  (chip_meta_live.get("pcb_pic", "") or "").strip(),
        "bond_pic": (chip_meta_live.get("bond_pic", "") or "").strip(),
        "pcb_type": (chip_meta_live.get("pcb_type", "") or "").strip(),
        "notion":   (chip_meta_live.get("notion", "") or "").strip(),
        "notes":    (chip_meta_live.get("notes", "") or "").strip(),
    }

    full_meta = copy.deepcopy(update_meta)
    full_meta.setdefault("package", {})
    full_meta["package"].setdefault("chips", {})

    existing = full_meta["package"]["chips"].get(chip_uid, {})

    # keeps pcb_ready / bond_date; updates only editable fields
    full_meta["package"]["chips"][chip_uid] = {**existing, **updated}

    firestore_set(
        "runs",
        loaded_run_doc_id,
        {
            "run_no": fields["run_no"]["stringValue"],
            "device_name": fields["device_name"]["stringValue"],
            "created_date": fields["created_date"]["stringValue"],
            "creator": fields["creator"]["stringValue"],
            "steps": update_layers,
            "metadata": full_meta,
        },
        id_token=id_token,
    )

    # sync cache
    update_meta["package"] = full_meta["package"]




def render_package_override(*, chip_uid, chip_label, chip_meta_live, fields, update_layers, update_meta, loaded_run_doc_id, id_token,):

    save_col, override_col = st.columns([1, 2])

    # -------------------------------
    # 💾 Normal Save (NO timestamps)
    # -------------------------------
    with save_col:
        if False:
            if st.button(
                "💾 Save Package Info",
                key=f"save_pkg_meta_{chip_uid}",
            ):


                save_package_info_core(
                    chip_uid=chip_uid,
                    chip_meta_live=chip_meta_live,
                    fields=fields,
                    update_layers=update_layers,
                    update_meta=update_meta,
                    loaded_run_doc_id=loaded_run_doc_id,
                    id_token=id_token,
                )

                st.success(f"Package metadata saved for {chip_label}")
                st.rerun()


    # -------------------------------
    # 🔁 Override Package timestamps
    # -------------------------------
    with override_col:
        chip_meta = (
            update_meta
            .setdefault("package", {})
            .setdefault("chips", {})
            .setdefault(chip_uid, {})
        )

        col_pcb, col_bond, col_deliv = st.columns(3)

        def render_pkg_override(col, key, label):
            with col:
                current_val = chip_meta.get(key, "")

                # if st.checkbox(
                #     f"Override {label}",
                #     key=f"ovr_pkg_{key}_{chip_uid}",
                # ):

                cb_key = f"ovr_pkg_{key}_{chip_uid}"
                pending_key = f"__pending_uncheck_{cb_key}"

                # ✅ apply deferred uncheck BEFORE checkbox creation
                if st.session_state.get(pending_key, False):
                    st.session_state[cb_key] = False
                    st.session_state[pending_key] = False

                if st.checkbox(
                    f"Override {label}",
                    key=cb_key,
                ):

                    default_val = (
                        current_val
                        if current_val
                        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )

                    new_val = st.text_input(
                        # f"{label} time (YYYY-MM-DD HH:MM:SS)",
                        "Date (YYYY-MM-DD HH:MM:SS)",
                        value=default_val,
                        key=f"text_pkg_{key}_{chip_uid}",
                    )

                    if st.button(
                        "Apply",
                        key=f"apply_pkg_{key}_{chip_uid}",
                    ):
                        try:
                            datetime.fromisoformat(new_val)

                            update_meta \
                                .setdefault("package", {}) \
                                .setdefault("chips", {}) \
                                .setdefault(chip_uid, {})[key] = new_val

                            firestore_update_field(
                                "runs",
                                loaded_run_doc_id,
                                f"metadata.package.chips.{chip_uid}.{key}",
                                new_val,
                                id_token,
                            )

                            st.success(f"{label} updated")
                            st.session_state[pending_key] = True
                            st.rerun()

                        except ValueError:
                            st.error("Invalid datetime format (YYYY-MM-DD HH:MM:SS)")

        # ✅ 3 overrides in one row
        render_pkg_override(col_pcb,   "pcb_ready",     "PCB Ready")
        render_pkg_override(col_bond,  "bond_date",     "Bond Date")
        render_pkg_override(col_deliv, "delivery_time", "Delivery Date")



########################################################
########################################################


def save_measure_info_core(
    *,
    fridge_uid,
    fridge_meta_live,
    fields,
    update_layers,
    update_meta,
    loaded_run_doc_id,
    id_token,
):

    updated = {
        "owner": (fridge_meta_live.get("owner", "") or "").strip(),
        "chip_uid": (fridge_meta_live.get("chip_uid", "") or "").strip(),
        "cell_type": (fridge_meta_live.get("cell_type", "") or "").strip(),
        # "notion": (fridge_meta_live.get("notion", "") or "").strip(),
        "notes": (fridge_meta_live.get("notes", "") or "").strip(),
    }

    full_meta = copy.deepcopy(update_meta)

    # 🔒 schema guard (legacy safety)
    if not isinstance(full_meta.get("measure"), dict):
        full_meta["measure"] = {}

    full_meta.setdefault("measure", {})
    full_meta["measure"].setdefault("fridges", {})

    existing = full_meta["measure"]["fridges"].get(fridge_uid, {})

    # ---------------------------------------------------------
    # 🔒 Notion is event-driven: NEVER wipe it from a save
    # If existing notion exists, preserve it unconditionally.
    # ---------------------------------------------------------
    if isinstance(existing, dict):
        n_existing = (existing.get("notion") or existing.get("Notion") or "").strip()
        if n_existing:
            existing = dict(existing)  # avoid mutating the original reference
            existing["notion"] = n_existing
            if "Notion" in existing:
                del existing["Notion"]

    # preserves timestamps; overwrites editable fields
    full_meta["measure"]["fridges"][fridge_uid] = {**existing, **updated}

    cur = full_meta["measure"]["fridges"][fridge_uid]
  
    firestore_set(
        "runs",
        loaded_run_doc_id,
        {
            "run_no": fields["run_no"]["stringValue"],
            "device_name": fields["device_name"]["stringValue"],
            "created_date": fields["created_date"]["stringValue"],
            "creator": fields["creator"]["stringValue"],
            "steps": update_layers,
            "metadata": full_meta,
        },
        id_token=id_token,
    )

    # 🔒 sync cache
    update_meta["measure"] = full_meta["measure"]



def render_measure_override(
    *,
    fridge_uid,
    fridge_label,
    fridge_meta_live,
    fields,
    update_layers,
    update_meta,
    loaded_run_no,
    loaded_run_doc_id,
    id_token,
):
    save_col, override_col = st.columns([1, 4])

    with save_col:
        if False:
            if st.button(
                "💾 Save Measurement Info",
                key=f"save_meas_meta_{fridge_uid}",
            ):
                save_measure_info_core(
                    fridge_uid=fridge_uid,
                    fridge_meta_live=fridge_meta_live,
                    fields=fields,
                    update_layers=update_layers,
                    update_meta=update_meta,
                    loaded_run_doc_id=loaded_run_doc_id,
                    id_token=id_token,
                )

                st.success(f"Measurement metadata saved for {fridge_label}")
                st.rerun()

    
    # ------------------------------------------------
    # 🔁 Override Measurement timestamps
    # ------------------------------------------------
  
    with override_col:
        meas_meta = (
            update_meta
            .get("measure", {})
            .get("fridges", {})
            .get(fridge_uid, {})
        )

        # # 3 columns: Cooldown | Measure | Warmup
        # col_cd, col_meas, col_warm = st.columns(3)
        # ------------------------------------------------
        # Override row (single line)
        # ------------------------------------------------
        col_cd, col_meas, col_warm, col_storage = st.columns(4)


        def render_phase_override(col, phase_label, phase_key):
            with col:

                cb_key = f"ovr_meas_{phase_key}_{loaded_run_doc_id}_{fridge_uid}"
                pending_key = f"__pending_uncheck_{cb_key}"

                # ✅ apply deferred uncheck BEFORE checkbox creation
                if st.session_state.get(pending_key, False):
                    st.session_state[cb_key] = False
                    st.session_state[pending_key] = False

                if st.checkbox(
                    f"Override {phase_label}",
                    key=f"ovr_meas_{phase_key}_{loaded_run_doc_id}_{fridge_uid}",
                ):

                    for suffix in ("start", "end"):
                        meta_key = f"{phase_key}_{suffix}"
                        # label = f"{phase_label} {suffix.capitalize()}"
                        label = f"{suffix.capitalize()}"


                        current_val = meas_meta.get(meta_key, "")
                        new_val = st.text_input(
                            f"{label} (YYYY-MM-DD HH:MM:SS)",
                            value=current_val or datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            key=f"text_meas_{meta_key}_{loaded_run_doc_id}_{fridge_uid}",
                        )

                        if st.button(
                            f"Apply",
                            # f"Apply {label}",
                            key=f"apply_meas_{meta_key}_{loaded_run_doc_id}_{fridge_uid}",
                        ):

                            try:
                                datetime.fromisoformat(new_val)

                                update_meta \
                                    .setdefault("measure", {}) \
                                    .setdefault("fridges", {}) \
                                    .setdefault(fridge_uid, {})[meta_key] = new_val

                                firestore_update_field(
                                    "runs",
                                    loaded_run_doc_id,
                                    f"metadata.measure.fridges.{fridge_uid}.{meta_key}",
                                    new_val,
                                    id_token,
                                )


                                # ------------------------------------------------
                                # 🔁 Notion sync: Cooldown start override ONLY
                                # ------------------------------------------------
                                if phase_key == "cooldown" and suffix == "start":

                                    # 1) What this render thinks (may be stale)
                                    page_id  = (meas_meta.get("notion_page_id") or "").strip()
                                    page_url = (meas_meta.get("notion") or "").strip()

                                    # 2) What the live session state holds (canonical during UI actions)
                                    fr_live = (
                                        update_meta
                                        .get("measure", {})
                                        .get("fridges", {})
                                        .get(fridge_uid, {})
                                    )
                                    page_id_live  = (fr_live.get("notion_page_id") or "").strip()
                                    page_url_live = (fr_live.get("notion") or "").strip()

                                    # 3) Use whichever is non-empty (debug only)
                                    use_page_id  = page_id_live or page_id
                                    use_page_url = page_url_live or page_url

                                    # 4) Firestore fallback (source of truth) if URL is missing in memory
                                    if use_page_id and (not use_page_url):
                                        try:
                                            run_doc = firestore_get("runs", loaded_run_doc_id, id_token)
                                            meta_fs = firestore_to_python((run_doc or {}).get("fields", {}).get("metadata", {}))
                                            fr_fs = (
                                                meta_fs.get("measure", {})
                                                .get("fridges", {})
                                                .get(fridge_uid, {})
                                            )

                                            fs_page_url = (fr_fs.get("notion") or "").strip()
                                            fs_page_id  = (fr_fs.get("notion_page_id") or "").strip()

                                            if fs_page_id:
                                                use_page_id = fs_page_id
                                            if fs_page_url:
                                                use_page_url = fs_page_url

                                            # keep session_state in sync for future reruns
                                            if fs_page_url:
                                                update_meta \
                                                    .setdefault("measure", {}) \
                                                    .setdefault("fridges", {}) \
                                                    .setdefault(fridge_uid, {})["notion"] = fs_page_url
                                            if fs_page_id:
                                                update_meta \
                                                    .setdefault("measure", {}) \
                                                    .setdefault("fridges", {}) \
                                                    .setdefault(fridge_uid, {})["notion_page_id"] = fs_page_id

                                        except Exception as e:
                                            st.warning(f"[DBG] Firestore fallback read failed (non-blocking): {e}")

                                    # ✅ INSERT START
                                    if (current_val or "").strip() == (new_val or "").strip():
                                        st.caption("[DBG] cooldown_start unchanged -> skip Notion sync")
                                    # ✅ INSERT END

                                    elif not use_page_id or not use_page_url:
                                        st.caption("[DBG] SKIP: missing page_id or page_url")
                                    else:
                                        try:
                                            got = run_notion_subprocess(
                                                script_path="notion/notion_get_page.py",
                                                payload={"page_id": use_page_id},
                                            )

                                            notion_iso = (got.get("cooldown_start_iso") or "").strip()
                                            notion_local = notion_utc_iso_to_fb_local_str(notion_iso)

                                            if notion_local != new_val:
                                                utc_iso = fb_local_str_to_notion_utc_iso(new_val)
                                                upd = run_notion_subprocess(
                                                    script_path="notion/notion_update_page.py",
                                                    payload={
                                                        "db_url": _pick_meas_db_url(fridge_label),
                                                        "page_url": use_page_url,
                                                        "properties": {
                                                            "Cooldown dates": utc_iso,  # STRING ONLY
                                                        },
                                                    },
                                                )
                                            else:
                                                st.caption("[DBG] no drift -> no notion update")

                                        except Exception as e:
                                            st.warning(f"[DBG] Notion cooldown override sync failed (non-blocking): {e}")


                                st.success(f"{label} updated")
                                st.session_state[pending_key] = True
                                st.rerun()
                                # st.stop()

                            except ValueError:
                                st.error(
                                    "Invalid datetime format (YYYY-MM-DD HH:MM:SS)"
                                )


        # Render 3 grouped override sections
        render_phase_override(col_cd,   "Cooldown", "cooldown")
        render_phase_override(col_meas, "Measure",  "measure")
        render_phase_override(col_warm, "Warmup",   "warmup")

        # ------------------------------------------------
        # ✅ Storage date override
        # ------------------------------------------------

        cb_key = f"ovr_meas_storage_time_{loaded_run_doc_id}_{fridge_uid}"
        pending_key = f"__pending_uncheck_{cb_key}"

        # ✅ apply deferred uncheck BEFORE checkbox creation
        if st.session_state.get(pending_key, False):
            st.session_state[cb_key] = False
            st.session_state[pending_key] = False

        with col_storage:
            if st.checkbox(
                "Override Storage date",
                key=f"ovr_meas_storage_time_{loaded_run_doc_id}_{fridge_uid}",
            ):
                current_val = meas_meta.get("storage_time", "")
                new_val = st.text_input(
                    "Date(YYYY-MM-DD HH:MM:SS)",
                    value=current_val or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    key=f"text_meas_storage_time_{loaded_run_doc_id}_{fridge_uid}",
                )

                if st.button(
                    "Apply",
                    key=f"apply_meas_storage_time_{loaded_run_doc_id}_{fridge_uid}",
                ):
                    try:
                        datetime.fromisoformat(new_val)

                        update_meta \
                            .setdefault("measure", {}) \
                            .setdefault("fridges", {}) \
                            .setdefault(fridge_uid, {})["storage_time"] = new_val

                        firestore_update_field(
                            "runs",
                            loaded_run_doc_id,
                            f"metadata.measure.fridges.{fridge_uid}.storage_time",
                            new_val,
                            id_token,
                        )

                        st.success("Storage date updated")
                        st.session_state[pending_key] = True
                        st.rerun()

                    except ValueError:
                        st.error("Invalid datetime format (YYYY-MM-DD HH:MM:SS)")





########################################################
########################################################



def render_metadata_ui(
    *,
    loaded_run_no,
    loaded_run_doc_id,
    fields,
    layers_py,
    update_layers,
    update_meta,
    save_full_run,
    id_token,
    stage_filter=None,
    key_prefix ="",
    hide_keys = (),
):
    """
    Render and handle all metadata editing UI.
    """

    # ----------------------------------------------------
    # DETAILED INFO EDITOR
    # ----------------------------------------------------

    DETAIL_ORDER = {
        "design": [
            "Creator",
            "Verifier",
            "Lotid",
            "Chip size (mm2)",
            "Spec",
            "Completed",
            "Notion",
            "File",
            "Notes",
        ],
        "fab": [
            "Owner",
            "Process",
            "Substrate",
            "Type",
            "Key feature",
            "Qty chips",
            "Notion",
            "Fabin",
            "Fabout",
            "Notes",
        ],
    }


    # # # Always use cached metadata for editing
    meta_py = update_meta

    # ✅ ALWAYS define this so later code can reference it
    design_meta_new = normalize_meta(update_meta.get("design", []))

    # ----------------------------------------------------
    # Stage filter: only render the section for this stage tab
    # stage_filter values: "design", "fab", "package", "measure" or None
    # ----------------------------------------------------
    stage = (stage_filter or "").strip().lower()

    show_design  = stage in ("", None, "design")
    show_fab     = stage in ("", None, "fab")
    show_package = stage in ("", None, "package")
    show_measure = stage in ("", None, "measure")


    if show_design:
        # design_meta_norm = normalize_meta(
        #     update_meta["design"]
        # )

        design_meta_norm = ensure_kv_rows(
            normalize_meta(update_meta["design"]),
            DETAIL_ORDER["design"],
        )



        design_footer=lambda: render_design_override(
            loaded_run_no=loaded_run_no,
            loaded_run_doc_id = loaded_run_doc_id,
            fields=fields,
            layers_py=layers_py,
            update_meta=update_meta,
            save_full_run=save_full_run,
            id_token=id_token,
        )

        design_meta_new = edit_metadata(
            "🎨 Design",
            design_meta_norm,
            disable_keys=("completed", "notion", "notion_page_id"),
            hide_keys=("file", "fileid", "filename", "filed"),
            render_footer=design_footer,
        )

        # 🔒 PRESERVE Completed from PRE-EDIT state
        old_completed = next(
            (r for r in design_meta_norm if r["key"].strip().lower() == "completed"),
            None
        )

        design_merged = [
            r for r in design_meta_new
            if r["key"].strip().lower() != "completed"
        ]

        if old_completed:
            design_merged.append(old_completed)

        # 🔑 single write-back
        update_meta["design"] = design_merged


    if show_fab:
        # fab_meta_norm = normalize_meta(update_meta["fab"])
        fab_meta_norm = ensure_kv_rows(
            normalize_meta(update_meta["fab"]),
            DETAIL_ORDER["fab"],
        )


        fab_footer=lambda: render_fab_override(
            loaded_run_no=loaded_run_no,
            loaded_run_doc_id=loaded_run_doc_id,
            fields=fields,
            layers_py=layers_py,
            update_meta=update_meta,
            save_full_run=save_full_run,
            id_token=id_token,
        )

        fab_meta_new = edit_metadata(
            "⚡ Fab",
            # meta_py["fab"],
            fab_meta_norm,
            skip_normalize=True,
            disable_keys=("fabin", "fabout", "notion", "notion_page_id"),
            hide_keys=(
                "file", "fileid", "filename", "filed", "fileid_", "filename_", "fab top callout", "fab child page ids",
                *hide_keys,   # ✅ ADD THIS
            ),
            render_footer=fab_footer,
        )


        # 🔒 PRESERVE Fabin / Fabout from PRE-EDIT state
        # old_fabin = next(
        #     (r for r in fab_meta_norm if r["key"].strip().lower() == "fabin"),
        #     None
        # )

        old_fabin = next(
            (r for r in update_meta["fab"] if r["key"].strip().lower() == "fabin"),
            None
        )



        old_fabout = next(
            (r for r in fab_meta_norm if r["key"].strip().lower() == "fabout"),
            None
        )

        fab_merged = [
            r for r in fab_meta_new
            if r["key"].strip().lower() not in ("fabin", "fabout")
        ]

        if old_fabin:
            fab_merged.append(old_fabin)

        if old_fabout:
            fab_merged.append(old_fabout)

        # 🔑 single write-back (IDENTICAL role to Design)
        update_meta["fab"] = fab_merged


    if show_package:
        chip_uid = None  # ✅ always defined

        pkg_chips = get_package_chips(update_layers)

        if not pkg_chips:
            st.info("No package chips defined in Package flow.")
        elif len(pkg_chips) != len(set(pkg_chips.keys())):
            st.error("Duplicate Package chip_uid detected. Flow is corrupted.")
        else:
            chip_uid = st.selectbox(
                "Select chip",
                options=list(pkg_chips.keys()),
                format_func=lambda uid: pkg_chips[uid],
                key=f"pkg_chip_sel_{loaded_run_doc_id}_{st.session_state['pkg_nonce']}",
            )

            # ✅ safe session write
            st.session_state["pkg_selected_chip_uid"] = chip_uid

            chip_label = pkg_chips[chip_uid]

            pkg_meta = update_meta.setdefault("package", {})
            chips_meta = pkg_meta.setdefault("chips", {})
            chip_meta = chips_meta.get(chip_uid, {})

            col1, col2, col3 = st.columns(3)

            with col1:
                pcb_pic = st.text_input(
                    "PCB Owner",
                    value=chip_meta.get("pcb_pic", ""),
                    key=f"pkg_pcb_pic_{chip_uid}",
                )
                bond_pic = st.text_input(
                    "Bonding Owner",
                    value=chip_meta.get("bond_pic", ""),
                    key=f"pkg_bond_pic_{chip_uid}",
                )

            with col2:
                pcb_type = st.text_input(
                    "PCB Type",
                    value=chip_meta.get("pcb_type", ""),
                    key=f"pkg_pcb_type_{chip_uid}",
                )
                st.text_input("Bond Date", value=chip_meta.get("bond_date", ""), disabled=True)

            with col3:
                st.text_input("PCB Ready", value=chip_meta.get("pcb_ready", ""), disabled=True)
                st.text_input("Delivery Date", value=chip_meta.get("delivery_time", ""), disabled=True)

            notion = st.text_input(
                "Notion",
                value=chip_meta.get("notion", ""),
                key=f"pkg_notion_{chip_uid}",
                disabled = True,
            )
            notes = st.text_area(
                "Notes",
                value=chip_meta.get("notes", ""),
                key=f"pkg_notes_{chip_uid}",
            )

            chips_meta[chip_uid] = {
                **chip_meta,
                "pcb_pic": pcb_pic,
                "bond_pic": bond_pic,
                "pcb_type": pcb_type,
                "notion": notion,
                "notes": notes,
            }
            chip_meta = chips_meta[chip_uid]

            chip_meta_live = {
                **chip_meta,
                "pcb_pic": pcb_pic,
                "bond_pic": bond_pic,
                "pcb_type": pcb_type,
                "notion": notion,
                "notes": notes,
            }

            render_package_override(
                chip_uid=chip_uid,
                chip_label=chip_label,
                chip_meta_live=chip_meta_live,
                fields=fields,
                update_layers=update_layers,
                update_meta=update_meta,
                loaded_run_doc_id=loaded_run_doc_id,
                id_token=id_token,
            )


    if show_measure:
            #------------------------------------------------
            # Measurement editor
            #------------------------------------------------

        # with st.expander("📈 Measurement", expanded=False):

            meas_fridges = get_measure_fridges(update_layers)

            if not meas_fridges:
                st.info("No fridges defined in Measurement flow.")
                return

            # get Measurement substeps in flow order
            meas_layer = next(
                l for l in update_layers if l.get("layer_name") == "Measurement"
            )
            flow_substeps = meas_layer.get("substeps", [])


            fridge_display = build_fridge_display_map(meas_fridges, flow_substeps)

            fridge_uid = st.selectbox(
                "Select fridge",
                options=list(meas_fridges.keys()),
                # format_func=lambda uid: meas_fridges[uid],
                # format_func=lambda uid: f"{meas_fridges[uid]} [{uid[-4:]}]",
                format_func=lambda uid: fridge_display[uid],
                key=f"meas_fridge_sel_{loaded_run_doc_id}_{st.session_state['meas_nonce']}",
            )


            st.session_state["meas_prev_fridge_uid"] = fridge_uid




            # --------------------------------------------------
            # ONLY NOW it is safe to render widgets / debug
            # --------------------------------------------------

            # (optional debug — safe here)
            # st.write("DEBUG fridge:", fridge_uid)

            # ✅ Package-style: always use LIVE refs
            if not isinstance(update_meta.get("measure"), dict):
                update_meta["measure"] = {}

            meas_meta = update_meta.get("measure", {})
            fridges_meta = meas_meta.get("fridges", {})
            fridge_meta = fridges_meta.get(fridge_uid, {})


            
            col1, col2, col3 = st.columns(3)

            with col1:
                owner = st.text_input(
                    "Owner",
                    value=fridge_meta.get("owner", ""),
                    key=f"meas_owner_{loaded_run_doc_id}_{fridge_uid}",
                )



            with col2:
                cell_type = st.text_input(
                    "Cell type",
                    value=fridge_meta.get("cell_type", ""),
                    key=f"meas_cell_{loaded_run_doc_id}_{fridge_uid}",
                )


            with col3:

                package_chips = get_package_chips(update_layers)
                pkg_meta = update_meta.get("package", {}).get("chips", {})

                chip_uid_list = list(package_chips.keys())

                chip_status = {
                    uid: bool(pkg_meta.get(uid, {}).get("bond_date"))
                    for uid in chip_uid_list
                }

                current_chip_uid = fridge_meta.get("chip_uid")

                if current_chip_uid in chip_uid_list:
                    chip_index = chip_uid_list.index(current_chip_uid)
                else:
                    chip_index = 0 if chip_uid_list else None

                selected_chip_uid = st.selectbox(
                    "Chip",
                    options=chip_uid_list,
                    index=chip_index,
                    format_func=lambda uid: (
                        package_chips[uid]
                        if chip_status.get(uid)
                        else f"{package_chips[uid]} (not bonded)"
                    ),
                    key=f"meas_chip_uid_{loaded_run_doc_id}_{fridge_uid}",
                )

                chip = selected_chip_uid



            new_col1, new_col2 = st.columns(2)

            with new_col1:

                st.text_input(
                    "Cooldown",
                    value=format_range(
                        fridge_meta.get("cooldown_start", ""),
                        fridge_meta.get("cooldown_end", ""),
                    ),
                    disabled=True,
                )

                st.text_input(
                    "Warmup",
                    value=format_range(
                        fridge_meta.get("warmup_start", ""),
                        fridge_meta.get("warmup_end", ""),
                    ),
                    disabled=True,
                )

            with new_col2:

                st.text_input(
                    "Measure",
                    value=format_range(
                        fridge_meta.get("measure_start", ""),
                        fridge_meta.get("measure_end", ""),
                    ),
                    disabled=True,
                )

                st.text_input(
                    "Storage date",
                    value=fridge_meta.get("storage_time", ""),
                    disabled=True,
                )



            notion = st.text_input(
                "Notion",
                value=fridge_meta.get("notion", ""),
                key=f"meas_notion_{loaded_run_doc_id}_{fridge_uid}",
                disabled = True,
            )

            notes = st.text_area(
                "Notes",
                value=fridge_meta.get("notes", ""),
                key=f"meas_notes_{loaded_run_doc_id}_{fridge_uid}",
            )


            # ✅ PUT THIS BLOCK RIGHT HERE
            meas_meta = update_meta.setdefault("measure", {})
            fridges_meta = meas_meta.setdefault("fridges", {})
            existing = fridges_meta.get(fridge_uid, {})

            fridges_meta[fridge_uid] = {
                **existing,          # keep cooldown/measure/warmup timestamps, storage, etc.
                "owner": owner,
                "chip_uid": chip,
                "cell_type": cell_type,
                "notion": notion,
                "notes": notes,
            }

            # (optional) keep local var in sync
            fridge_meta = fridges_meta[fridge_uid]


            fridge_meta_live = {
            **fridge_meta,
            "owner": owner,
            "chip_uid": chip,
            "cell_type": cell_type,
            "notion": notion,
            "notes": notes,
            }

            package_chips = get_package_chips(update_layers)
            pkg_meta = update_meta.get("package", {}).get("chips", {})
            chip_status = {}
            for uid in package_chips:
                bonded = bool(pkg_meta.get(uid, {}).get("bond_date"))
                chip_status[uid] = bonded

            render_measure_override(
                fridge_uid=fridge_uid,
                fridge_label=meas_fridges[fridge_uid],
                fridge_meta_live=fridge_meta_live,
                fields=fields,
                update_layers=update_layers,
                update_meta=update_meta,
                loaded_run_no=loaded_run_no,
                loaded_run_doc_id=loaded_run_doc_id,
                id_token=id_token,
            )

            # st.write("MEASUREMENT META END:", update_meta.get("measure"))


            # 🔒 Preserve auto-generated Completed timestamp
            old_design_meta = update_meta["design"]

            completed_row = next(
                (x for x in old_design_meta if x["key"].strip().lower() == "completed" and x["value"]),
                None
            )

            if completed_row:
                design_meta_new = [
                    x for x in design_meta_new
                    if x["key"].strip().lower() != "completed"
                ] + [completed_row]



