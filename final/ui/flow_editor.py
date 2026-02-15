import streamlit as st
import copy
import uuid

from services.flow_builder import ensure_flow_ids, ensure_chip_ids
from services.presets import save_layer_preset
from services.flow_defaults import get_default_layer

def make_unique_label(base, existing_labels):
    if base not in existing_labels:
        return base

    i = 1
    while f"{base} ({i})" in existing_labels:
        i += 1

    return f"{base} ({i})"


def flow_editor(layer_filter=None, ui_mode = "expander"):
    """
    UI for editing flow structure.
    Reads and mutates st.session_state["flow"]
    """
    flow = st.session_state["flow"]

    # --- NEW: optional layer filter (string or list[str]) ---
    if isinstance(layer_filter, str):
        layer_filter = [layer_filter]
    layer_filter_norm = (
        {s.strip().lower() for s in layer_filter}
        if layer_filter
        else None
    )


    if "active_preset" not in st.session_state:
        st.session_state["active_preset"] = {}   # stores active preset for each layer

    for layer_idx, layer in enumerate(flow):

        # --- NEW: skip other layers if filtered ---
        if layer_filter_norm is not None:
            name_norm = (layer.get("layer_name") or "").strip().lower()
            if name_norm not in layer_filter_norm:
                continue

        # with st.expander(f"{layer.get('icon','')} {layer['layer_name']}", expanded=False):
        if ui_mode == "expander":
            wrapper = st.expander(
                f"{layer.get('icon','')} {layer['layer_name']}",
                expanded=False
            )
        else:
            # st.markdown(f"##### {layer.get('icon','')} {layer['layer_name']}")
            # wrapper = st.container(border=True)
            # flat mode: no title, no boundary box
            wrapper = st.container()

        with wrapper:

            layer_label = layer["layer_name"]
            layer_name_norm = layer_label.strip().lower()

            is_entity_layer = layer_name_norm in ("package", "measurement")

            lock_measurement = (layer_name_norm == "measurement")
            lock_package     = (layer_name_norm == "package")
            lock_subfields   = is_entity_layer



            # ---------------------------
            # UNIVERSAL PRESET BAR
            # ---------------------------
            preset_names = [f"Preset {i}" for i in range(1, 6)]

            # preset_row = st.columns([0.20, 0.15, 0.15, 0.15])
            preset_row = st.columns([0.25, 0.15, 0.35, 0.25])


            # ------------------------------
            # Load Preset (dropdown + Apply)
            # ------------------------------
            layer_name = layer["layer_name"]

            # active preset index (0..4) or None
            active_idx = st.session_state.get("active_preset", {}).get(layer_name, None)

            # default dropdown selection = active preset if available
            default_i = active_idx if isinstance(active_idx, int) and 0 <= active_idx < 5 else 0

            # Options: "Default" + Preset 1..5
            apply_options = ["Default"] + list(range(5))

            # index: if an active preset exists, shift by +1 because "Default" is at index 0
            default_index = (active_idx + 1) if isinstance(active_idx, int) and 0 <= active_idx < 5 else 0

            with preset_row[0]:
                preset_choice = st.selectbox(
                    "Preset",
                    options=apply_options,
                    index=default_index,
                    format_func=lambda x: ("Default" if x == "Default" else preset_names[x]),
                    key=f"load_preset_choice_{layer_idx}",
                    label_visibility="collapsed",
                )


            with preset_row[1]:
                if st.button("Load", key=f"load_preset_apply_{layer_idx}"):

                    # --- Default ---
                    if preset_choice == "Default":
                        default_layer = get_default_layer(layer_name)
                        layer["substeps"] = copy.deepcopy(default_layer["substeps"])
                        ensure_flow_ids([layer])

                        # Clear active preset
                        st.session_state.setdefault("active_preset", {})
                        st.session_state["active_preset"][layer_name] = None

                        st.success(f"{layer_name} reset to default")
                        st.rerun()

                    # --- Preset 1..5 ---
                    else:
                        saved = st.session_state.get("layer_presets", {}).get(layer_name, {})
                        k = str(preset_choice)  # preset_choice is 0..4 here

                        if k in saved:
                            layer["substeps"] = copy.deepcopy(saved[k])
                            ensure_flow_ids([layer])

                            st.session_state.setdefault("active_preset", {})
                            st.session_state["active_preset"][layer_name] = int(preset_choice)

                            st.success(f"{layer_name} → Loaded {preset_names[preset_choice]}")
                            st.rerun()
                        else:
                            st.warning(f"{preset_names[preset_choice]} not saved yet.")



            # Optional: show active preset status (replaces ✅ on buttons)
            with preset_row[3]:
                if active_idx is not None:
                    st.caption(f"Active: {preset_names[active_idx]}")
                else:
                    st.caption("Active: Default")

            st.write("")


            with preset_row[2]:
                # Disable save if Default is selected
                save_disabled = (preset_choice == "Default")

                if st.button("Save Preset", key=f"save_preset_btn_{layer_idx}", disabled=save_disabled):
                    layer_name = layer["layer_name"]

                    # preset_choice is 0..4 here
                    slot_idx = str(int(preset_choice))  # "0".."4"

                    st.session_state.setdefault("layer_presets", {})
                    st.session_state["layer_presets"].setdefault(layer_name, {})

                    st.session_state["layer_presets"][layer_name][slot_idx] = copy.deepcopy(layer["substeps"])

                    # Persist to Firestore (your correct positional signature)
                    save_layer_preset(
                        layer_name,
                        slot_idx,
                        st.session_state["layer_presets"][layer_name][slot_idx],
                        st.session_state["user"]["idToken"],
                    )

                    # Mark active preset
                    st.session_state.setdefault("active_preset", {})
                    st.session_state["active_preset"][layer_name] = int(preset_choice)

                    st.success(f"Preset {int(preset_choice) + 1} saved for {layer_name}")
                    st.rerun()



            substeps = layer["substeps"]

            # -------- existing substeps --------
            for sub_idx, sub in enumerate(substeps):
                unique = sub["id"]

                # ===== Substep row =====
                # columns: [name field][del][add][spacer]
                # main_cols = st.columns([0.55, 0.05, 0.05, 0.35])
                main_cols = st.columns([0.15, 0.08, 0.05, 0.1])

                with main_cols[0]:

                    if "chip_uid" in sub or "fridge_uid" in sub:

                        # Measurement: dropdown (editable)
                        if lock_measurement and "fridge_uid" in sub:
                            cur = sub.get("label") or "ICEOxford"
                            sub_label = st.selectbox(
                                f"subname_{unique}",
                                options=["ICEOxford", "Bluefors"],
                                index=0 if cur == "ICEOxford" else 1,
                                key=f"meas_fridge_label_{unique}",
                                label_visibility="collapsed",
                            )
                            sub["label"] = sub_label

                        # All other cases: original behavior
                        else:
                            sub_label = st.text_input(
                                f"subname_{unique}",
                                value=sub.get("label") or sub.get("name", ""),
                                label_visibility="collapsed",
                                disabled=lock_measurement,   # 🔒 visible but locked
                            )
                            if sub_label.strip():
                                sub["label"] = sub_label.strip()


                    # Legacy name-based substeps (Design / Fab)
                    else:
                        sub_name = st.text_input(
                            f"subname_{unique}",
                            value=sub.get("name", ""),
                            label_visibility="collapsed",
                        )
                        if sub_name.strip():
                            sub["name"] = sub_name.strip()



                with main_cols[1]:
                    col_del, col_add = st.columns([1, 1])

                    with col_del:
                        # Measurement fridge delete (group-level) → ENABLED
                        if lock_measurement and "fridge_uid" in sub:
                            if st.button("✖", key=f"sub_del_{unique}", help="Delete fridge"):
                                if len(substeps) > 1:
                                    substeps.pop(sub_idx)
                                    st.rerun()

                        # All other cases (Design / Fab / Package OR substeps)
                        else:
                            if st.button(
                                "✖",
                                key=f"sub_del_{unique}",
                                help="Delete substep",
                                disabled=lock_measurement,
                            ):
                                if len(substeps) > 1:
                                    substeps.pop(sub_idx)
                                    st.rerun()

                    with col_add:
                        if st.button(
                            "✚",
                            key=f"sub_add_{unique}",
                            help="Add chip",
                            disabled=lock_subfields,  # Package + Measurement: disabled
                            # disabled=chips_locked,
                        ):
                            sub["chips"].append({"name": "New chip"})
                            st.rerun()





                # ===== Chip rows (indented) =====
                chips = sub["chips"]
                for chip_idx, chip in enumerate(chips):
                    # columns: [indent][chip name][del][spacer]

                    chip_cols = st.columns([0.07, 0.30, 0.15, 0.2])

                    # indent column (empty)
                    _ = chip_cols[0]

                    with chip_cols[1]:
                        # chip_name = st.text_input(
                        #     f"chipname_{unique}_{chip_idx}",
                        #     value=chip["name"],
                        #     label_visibility="collapsed",
                        # )

                        chip_name = st.text_input(
                            f"chipname_{unique}_{chip_idx}",
                            value=chip["name"],
                            label_visibility="collapsed",
                            # disabled=(lock_measurement or lock_package),
                            disabled=lock_subfields,
                        )

                        if chip_name.strip():
                            chip["name"] = chip_name.strip()

                    with chip_cols[2]:
                 
                        if st.button(
                            "✖",
                            key=f"chip_del_{unique}_{chip_idx}",
                            help="Delete chip",
                            # disabled=(lock_measurement or lock_package) or len(chips) == 1,
                            disabled=lock_subfields or len(chips) == 1,

                        ):

                            if len(chips) > 1:
                                chips.pop(chip_idx)
                                st.rerun()


            # -------- Add new substep --------
            # st.markdown("---")
            st.markdown(
                "<hr style='margin:4px 0; border:0; border-top:1px solid #e5e5e5;' />",
                unsafe_allow_html=True,
            )


            if st.button("Add step", key=f"add_substep_layer_{layer_idx}"):
            # if st.button(
            #     "Add step",
            #     key=f"add_substep_layer_{layer_idx}",
            #     disabled=lock_measurement,
            # ):


                if layer["layer_name"] == "Package":
                    substeps.append(
                        {
                            "id": str(uuid.uuid4()),
                            "chip_uid": f"chip_{uuid.uuid4().hex[:8]}",
                            "label": "C??",
                            "chips": [
                                {"name": "PCB"},
                                {"name": "Bonding"},
                                {"name": "Delivery"},

                            ],
                        }
                    )
                
                elif layer["layer_name"] == "Measurement":

                    # 🔑 Reuse fridge_uid if label already exists
                    existing = {
                        sub.get("label"): sub.get("fridge_uid")
                        for sub in substeps
                        if sub.get("fridge_uid")
                    }

                    label = "New Fridge"
                    fridge_uid = existing.get(label, f"fridge_{uuid.uuid4().hex[:8]}")

                    substeps.append(
                        {
                            "id": str(uuid.uuid4()),
                            "fridge_uid": fridge_uid,
                            "label": label,
                            "chips": [
                                # {"name": "Electrical check"},
                                {"name": "Cooldown"},
                                {"name": "Measure"},
                                {"name": "Warmup"},
                                {
                                    "name": "Storage",
                                    "type": "storage",
                                    "status": "pending",
                                },
                            ],
                        }
                    )


                # Design/Fab
                else:
                    # ORIGINAL behavior — untouched
                    substeps.append(
                        {
                            "id": str(uuid.uuid4()),
                            "name": "New substep",
                            "chips": [{"name": "New chip"}],
                        }
                    )

                st.rerun()


def update_flow_editor(layers, *, layer_filter=None, show_layer_tabs=True, key_prefix="updflow"):
    """
    Flow editor used in UPDATE RUN.
    - show_layer_tabs=True  -> current behavior (tabs across all layers)
    - show_layer_tabs=False -> render only the filtered layer (for stage-first UI)
    """
    ensure_chip_ids(layers)


    def _layer_all_pending(layer: dict) -> bool:
        for sub in (layer.get("substeps") or []):
            for ch in (sub.get("chips") or []):
                if (ch.get("status") or "").strip().lower() != "pending":
                    return False
        return True


    # ---------------------------
    # Optional: filter to one layer
    # ---------------------------
    layers_to_show = layers
    if layer_filter:
        want = layer_filter.strip().lower()
        layers_to_show = [
            l for l in layers
            if (l.get("layer_name") or "").strip().lower() == want
        ]

    if not layers_to_show:
        st.info("No matching layer found.")
        return

    # ---------------------------
    # Pick wrappers (tabs vs direct)
    # ---------------------------
    if show_layer_tabs and len(layers_to_show) > 1:
        wrappers = st.tabs([l["layer_name"] for l in layers_to_show])
    else:
        # wrappers = [st.container()] * len(layers_to_show)
        wrappers = [st.container() for _ in layers_to_show]


    for local_idx, layer in enumerate(layers_to_show):
        # ✅ Use layer_name in keys to avoid collisions across stage tabs
        layer_key = (layer.get("layer_name") or f"layer{local_idx}").strip().lower()

        layer_name = (layer.get("layer_name") or "").strip().lower()

        #### old
        # lock_measurement = (layer_name == "measurement")
        # lock_package     = (layer_name == "package")

        # lock_flow = not _layer_all_pending(layer)

        lock_measurement = (layer_name == "measurement")
        lock_package     = (layer_name == "package")
        lock_design      = (layer_name == "design")
        lock_fab         = (layer_name == "fabrication")

        # Stage-level lock only for Design & Fab
        lock_flow = (lock_design or lock_fab) and (not _layer_all_pending(layer))




        with wrappers[local_idx]:
            substeps = layer["substeps"]

            layer_name = (layer.get("layer_name") or "").strip()
            lock_measurement = layer_name.lower() == "measurement"
            measurement_stage_locked = False

            # --------------------------------------------------
            # Stage lock banner (Design / Fabrication)
            # --------------------------------------------------
            if layer_name.lower() in ("design", "fabrication") and lock_flow:
                st.info(
                    "Flow is locked because work has started. "
                    "Once all statuses return to pending, it becomes editable again."
                )


            # --------------------------------------------------
            # Package lock hint (per-chip groups)
            # --------------------------------------------------
            if layer_name.lower() == "package":
                any_locked = any(
                    not all((ch.get("status") or "").strip().lower() == "pending"
                            for ch in sub.get("chips", []))
                    for sub in substeps
                )
                if any_locked:
                    st.info(
                        "Some chip groups are locked because processing has started. "
                        "Groups become editable again if all statuses return to pending."
                    )


            # --------------------------------------------------
            # Measurement: info when fridge labels are locked
            # --------------------------------------------------
            if lock_measurement:
                fridges_meta = (
                    st.session_state
                    .get("update_meta", {})
                    .get("measure", {})
                    .get("fridges", {})
                )

                any_cooldown_started = any(
                    (meta.get("cooldown_start", "") or "").strip()
                    for meta in fridges_meta.values()
                    if isinstance(meta, dict)
                )

                if any_cooldown_started:
                    st.info(
                        "Fridge group is not editable once cooldown has started. "
                        "Only if all statuses go back to pending, it becomes editable."
                    )

                # measurement_stage_locked = lock_measurement and any_cooldown_started


            delete_sub = None
            delete_chip = None
            add_chip_target = None

            # ------------------------------------------------------------
            # Measurement fridge captions: Bluefors (1), Bluefors (2), ...
            # Derived from current flow order (viewer-consistent)
            # ------------------------------------------------------------
            base_labels = [
                s.get("label") or s.get("name") or "Unknown"
                for s in substeps
            ]

            label_counts = {}
            for lbl in base_labels:
                label_counts[lbl] = label_counts.get(lbl, 0) + 1

            label_indices = {}
            display_labels = []

            for lbl in base_labels:
                if label_counts[lbl] > 1:
                    label_indices[lbl] = label_indices.get(lbl, 0) + 1
                    display_labels.append(f"{lbl} ({label_indices[lbl]})")
                else:
                    display_labels.append(lbl)


            # ---- Substeps ----
            for sub_idx, sub in enumerate(substeps):

                # 🔒 Package per-substep lock
                sub_all_pending = all(
                    (ch.get("status") or "").strip().lower() == "pending"
                    for ch in sub.get("chips", [])
                )

                # is_pkg_or_meas = layer_name.lower() in ("package", "measurement")
                # chips_locked = (
                #     lock_flow                     # full stage lock always wins
                #     or (is_pkg_or_meas and sub_all_pending)
                # )

                is_pkg_or_meas = layer_name.lower() in ("package", "measurement")
                layer_all_pending = _layer_all_pending(layer)

                chips_locked = (
                    lock_flow
                    or (is_pkg_or_meas and (sub_all_pending or not layer_all_pending))
                )



                # cols = st.columns([0.5, 0.1, 0.1, 0.3])
                cols = st.columns([0.30, 0.1, 0.1, 0.50])

                with cols[0]:

                    if "chip_uid" in sub or "fridge_uid" in sub:

                        # --------------------------------------------------
                        # Measurement: fridge label locked after cooldown_start
                        # --------------------------------------------------
                        if lock_measurement and "fridge_uid" in sub:

                            fridge_uid = sub.get("fridge_uid")

                            fridge_meta = (
                                st.session_state
                                .get("update_meta", {})
                                .get("measure", {})
                                .get("fridges", {})
                                .get(fridge_uid, {})
                            )

                            cooldown_started = bool(
                                (fridge_meta.get("cooldown_start", "") or "").strip()
                            )

                            # --------------------------------------------
                            # Fridge mutability rule:
                            # All chip statuses must be pending
                            # --------------------------------------------
                            all_pending = all(
                                (ch.get("status") or "").strip().lower() == "pending"
                                for ch in sub.get("chips", [])
                            )

                            cur = sub.get("label") or "ICEOxford"
                            new_label = st.selectbox(
                                f"{key_prefix}_subname_{layer_key}_{sub_idx}",
                                options=["ICEOxford", "Bluefors"],
                                index=0 if cur == "ICEOxford" else 1,
                                label_visibility="collapsed",
                                # disabled=cooldown_started, 
                                # disabled=lock_flow,
                                disabled=not all_pending, 
                            )

                            ######### debugging
                            # old_label = sub.get("label")

                            # if old_label != new_label:
                            #     st.warning(
                            #         f"[DBG3] LABEL CHANGE uid={sub.get('fridge_uid')} "
                            #         f"'{old_label}' → '{new_label}' (user-driven)"
                            #     )
                            # else:
                            #     st.warning(
                            #         f"[DBG3] LABEL NO-OP uid={sub.get('fridge_uid')} "
                            #         f"'{old_label}' (rerun / relog)"
                            #     )


                            # sub["label"] = new_label
                            if (sub.get("label") or "") != (new_label or ""):
                                sub["label"] = new_label

                            # ------------------------------------------------------------
                            # 🔥 If fridge label changes and cooldown has not started,
                            #     clear stale Notion pointers immediately
                            # ------------------------------------------------------------
                            fridge_uid = sub.get("fridge_uid")

                            fridge_meta = (
                                st.session_state
                                .setdefault("update_meta", {})
                                .setdefault("measure", {})
                                .setdefault("fridges", {})
                                .setdefault(fridge_uid, {})
                            )


                        # All other cases → original text input
                        else:
                            new_label = st.text_input(
                                f"{key_prefix}_subname_{layer_key}_{sub_idx}",
                                value=sub.get("label") or sub.get("name", ""),
                                label_visibility="collapsed",
                                # disabled=lock_measurement,
                                # disabled=lock_flow,
                                disabled=lock_flow if not lock_package else not sub_all_pending,
                            )
                            if new_label.strip():
                                sub["label"] = new_label.strip()



                    # Legacy Design / Fab
                    else:
                        new_name = st.text_input(
                            f"{key_prefix}_subname_{layer_key}_{sub_idx}",
                            value=sub.get("name", ""),
                            label_visibility="collapsed",
                            disabled=lock_flow,
                        )
                        if new_name.strip():
                            sub["name"] = new_name.strip()


                with cols[1]:
                    # Measurement fridge delete (group-level) → ENABLED
                    if lock_measurement and "fridge_uid" in sub:

                        # --------------------------------------------
                        # Fridge mutability rule:
                        # All chip statuses must be pending
                        # --------------------------------------------
                        all_pending = all(
                            (ch.get("status") or "").strip().lower() == "pending"
                            for ch in sub.get("chips", [])
                        )


                        if lock_measurement and "fridge_uid" in sub:

                            if st.button(
                                "✖",
                                key=f"{key_prefix}_del_sub_{layer_key}_{sub_idx}",
                                disabled=not all_pending,
                            ):
                                if len(substeps) == 1:
                                    st.toast(
                                        "Cannot remove the only fridge group. "
                                        "To change the fridge type, first add another fridge, then remove this one."
                                    )
                                else:
                                    delete_sub = sub_idx

                            # if not all_pending:
                            #     st.toast("All statuses must be pending to delete this fridge.")


                    # All other cases → disabled for Measurement
                    else:
                        if st.button(
                            "✖",
                            key=f"{key_prefix}_del_sub_{layer_key}_{sub_idx}",
                            disabled=lock_flow if not lock_package else not sub_all_pending,

                        ):
                            delete_sub = sub_idx

                with cols[2]:
                    if st.button(
                        "✚",
                        key=f"{key_prefix}_add_chip_{layer_key}_{sub_idx}",
                        # disabled=(
                        #     (lock_measurement and not sub_all_pending)   # 🔒 per-fridge lock
                        #     or (lock_flow if not lock_package else not sub_all_pending)
                        # ),
                        disabled=chips_locked,

                    ):
                        add_chip_target = sub_idx

                with cols[3]:
                    st.caption(display_labels[sub_idx])



                # ---- Chips ----
                for chip_idx, chip in enumerate(sub["chips"]):
                    # cc = st.columns([0.1, 0.5, 0.2, 0.2])
                    cc = st.columns([0.1, 0.30, 0.25, 0.35])

                    with cc[1]:
        
                        chip_name = st.text_input(
                            f"{key_prefix}_chipname_{layer_key}_{sub_idx}_{chip_idx}",
                            value=chip["name"],
                            label_visibility="collapsed",
                            # disabled=(
                            #     (lock_measurement and not sub_all_pending)   # 🔒 per-fridge
                            #     or (lock_flow and not lock_package)          # design/fab stage lock
                            #     or (lock_package and not sub_all_pending)    # package per-substep
                            # )
                            disabled=chips_locked,
                        )
                        if chip_name.strip():
                            chip["name"] = chip_name.strip()


                    with cc[2]:

                        if st.button(
                            "✖",
                            key=f"{key_prefix}_del_chip_{layer_key}_{sub_idx}_{chip_idx}",
                            # disabled=(
                            #     len(sub["chips"]) == 1
                            #     or (lock_measurement and not sub_all_pending)   # 🔒 per-fridge
                            #     or (lock_flow and not lock_package)
                            #     or (lock_package and not sub_all_pending)
                            # )
                            disabled=(len(sub["chips"]) == 1 or chips_locked)
                        ):
                            delete_chip = (sub_idx, chip_idx)


            # ---- Add Substep ----
            if st.button("➕ Add Step", 
                key=f"{key_prefix}_add_substep_{layer_key}", 
                disabled=lock_flow):

                if layer["layer_name"] == "Package":
                    substeps.append({
                        "chip_uid": f"chip_{uuid.uuid4().hex[:8]}",
                        "label": "C??",
                        "chips": [
                            {"name": "PCB", "status": "pending"},
                            {"name": "Bonding", "status": "pending"},
                            {"name": "Delivery", "type": "delivery", "status": "pending"},
                        ],
                    })

                elif layer["layer_name"] == "Measurement":
                    substeps.append({
                        "fridge_uid": f"fridge_{uuid.uuid4().hex[:8]}",
                        "label": "New Fridge",
                        "chips": [
                            {"name": "Cooldown", "status": "pending"},
                            {"name": "Measure", "status": "pending"},
                            {"name": "Warmup", "status": "pending"},
                            {"name": "Storage", "type": "storage", "status": "pending"},
                        ],
                    })

                else:
                    substeps.append({
                        "name": "New substep",
                        "chips": [{"name": "New chip", "status": "pending"}],
                    })

                st.rerun()

            # ---- Apply changes ----
            if add_chip_target is not None:
                substeps[add_chip_target]["chips"].append({"name": "New chip", "status": "pending"})
                st.rerun()

            if delete_chip is not None:
                si, ci = delete_chip
                if len(substeps[si]["chips"]) > 1:
                    substeps[si]["chips"].pop(ci)
                st.rerun()

            if delete_sub is not None and len(substeps) > 1:
                substeps.pop(delete_sub)
                st.rerun()
