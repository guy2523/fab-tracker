# services/timestamps.py

from firebase_client import firestore_update_field


# ============================================================
# CHIP STATUS → started_at / completed_at
# ============================================================

def apply_chip_status_transition(chip_ref, old_status, new_status, now):
    """
    Apply status transition side-effects to a chip dict.

    chip_ref: dict (the actual chip object in layers_py)
    old_status, new_status: strings
    now: timestamp string (YYYY-MM-DD HH:MM:SS)

    This function ONLY mutates chip_ref.
    """

    # ---------------------------------------------
    # 1. pending → in_progress
    # ---------------------------------------------
    if old_status == "pending" and new_status == "in_progress":
        chip_ref["started_at"] = now
        chip_ref.pop("completed_at", None)

    # ---------------------------------------------
    # 2. in_progress → done
    # ---------------------------------------------
    elif old_status == "in_progress" and new_status == "done":
        chip_ref["completed_at"] = now
        
    # ---------------------------------------------
    # 3. pending → done  (skip-safe)
    # ---------------------------------------------
    elif old_status == "pending" and new_status == "done":
        chip_ref["started_at"] = now
        chip_ref["completed_at"] = now

    # ---------------------------------------------
    # 4. done → in_progress  (reset + restart)
    # ---------------------------------------------
    elif old_status == "done" and new_status == "in_progress":
        chip_ref.pop("completed_at", None)
        chip_ref["started_at"] = now

    # ---------------------------------------------
    # 5. done → pending  (full reset)
    # ---------------------------------------------
    elif old_status == "done" and new_status == "pending":
        chip_ref.pop("completed_at", None)
        chip_ref.pop("started_at", None)

    # ---------------------------------------------
    # 6. in_progress → pending  (reset start)
    # ---------------------------------------------
    elif old_status == "in_progress" and new_status == "pending":
        chip_ref.pop("started_at", None)
        chip_ref.pop("completed_at", None)
    # -----------------------------------------------------




# ============================================================
# PACKAGE: PCB Ready / Bond Date (chip-centric, auto)
# ============================================================


def apply_package_auto_dates(
    layer_name,
    chip_name,
    chip_uid,
    old_status,
    new_status,
    update_meta,
    loaded_run_doc_id,
    id_token,
    now,
):
    """
    Auto-set / clear Package timestamps (PCB Ready, Bond Date).
    Behavior is IDENTICAL to admin.py logic.
    """

    # Only applies to Package layer
    if layer_name.lower() != "package":
        return

    if not chip_uid:
        return

    # chip_name = ch.get("name", "").lower()
    chip_name = (chip_name or "").lower()

    # ensure local cache exists
    pkg = update_meta.setdefault("package", {})
    chips_meta = pkg.setdefault("chips", {})
    chip_meta = chips_meta.setdefault(chip_uid, {})

    # -----------------------------
    # PCB chip
    # -----------------------------
    if chip_name == "pcb":

        if old_status != "done" and new_status == "done":
            # 🔒 Only auto-set if not already present (no override)
            if not chip_meta.get("pcb_ready"):
                chip_meta["pcb_ready"] = now

                firestore_update_field(
                    "runs",
                    loaded_run_doc_id,
                    f"metadata.package.chips.{chip_uid}.pcb_ready",
                    now,
                    id_token,
                )


        # done → not done
        elif old_status == "done" and new_status != "done":
            chip_meta.pop("pcb_ready", None)

            firestore_update_field(
                "runs",
                loaded_run_doc_id,
                f"metadata.package.chips.{chip_uid}.pcb_ready",
                "",
                id_token,
            )


    # -----------------------------
    # Bonding chip
    # -----------------------------
    elif chip_name in ("bond", "bonding"):

        if old_status != "done" and new_status == "done":
            if not chip_meta.get("bond_date"):
                chip_meta["bond_date"] = now

                firestore_update_field(
                    "runs",
                    loaded_run_doc_id,
                    f"metadata.package.chips.{chip_uid}.bond_date",
                    now,
                    id_token,
                )


        # done → not done
        elif old_status == "done" and new_status != "done":
            chip_meta.pop("bond_date", None)

            firestore_update_field(
                "runs",
                loaded_run_doc_id,
                f"metadata.package.chips.{chip_uid}.bond_date",
                "",
                id_token,
            )



def apply_measurement_auto_dates(
    layer_name,
    chip_name,
    chip_uid,
    old_status,
    new_status,
    update_meta,
    now,
):
    # Measurement only
    if layer_name.lower() != "measurement":
        return

    if not chip_uid:
        return

    chip_name = (chip_name or "").lower()

    measure = update_meta.setdefault("measure", {})
    fridges = measure.setdefault("fridges", {})
    fridge_meta = fridges.setdefault(chip_uid, {})

    # def handle_interval(start_key, end_key):
    #     if old_status == "pending" and new_status == "in_progress":
    #         fridge_meta[start_key] = now
    #         fridge_meta.pop(end_key, None)

    #     elif old_status == "pending" and new_status == "done":
    #         fridge_meta[start_key] = now
    #         fridge_meta[end_key] = now

    #     elif old_status == "in_progress" and new_status == "done":
    #         fridge_meta[end_key] = now

    #     elif old_status == "in_progress" and new_status == "pending":
    #         fridge_meta.pop(start_key, None)
    #         fridge_meta.pop(end_key, None)

    #     elif old_status == "done" and new_status == "in_progress":
    #         fridge_meta[start_key] = now
    #         fridge_meta.pop(end_key, None)

    #     elif old_status == "done" and new_status == "pending":
    #         fridge_meta.pop(start_key, None)
    #         fridge_meta.pop(end_key, None)

    def handle_interval(start_key, end_key):

        old = (old_status or "").lower()
        new = (new_status or "").lower()

        inactive = ("pending", "terminate")

        # -------------------------
        # START
        # -------------------------
        if old in inactive and new == "in_progress":
            fridge_meta[start_key] = now
            fridge_meta.pop(end_key, None)

        # -------------------------
        # DIRECT COMPLETE
        # -------------------------
        elif old in inactive and new == "done":
            fridge_meta[start_key] = now
            fridge_meta[end_key] = now

        # -------------------------
        # COMPLETE FROM IN_PROGRESS
        # -------------------------
        elif old == "in_progress" and new == "done":
            fridge_meta[end_key] = now

        # -------------------------
        # RESET (enter inactive)
        # -------------------------
        elif new in inactive:
            fridge_meta.pop(start_key, None)
            fridge_meta.pop(end_key, None)

        # -------------------------
        # REOPEN FROM DONE
        # -------------------------
        elif old == "done" and new == "in_progress":
            fridge_meta[start_key] = now
            fridge_meta.pop(end_key, None)


    if chip_name == "cooldown":
        handle_interval("cooldown_start", "cooldown_end")

    elif chip_name == "measure":
        handle_interval("measure_start", "measure_end")

    elif chip_name == "warmup":
        handle_interval("warmup_start", "warmup_end")




# def apply_interval_transition(
#     *,
#     old_status,
#     new_status,
#     row,
#     start_key,
#     end_key,
#     now,
# ):
#     if old_status == "pending" and new_status == "in_progress":
#         row[start_key] = now
#         row.pop(end_key, None)

#     elif old_status == "pending" and new_status == "done":
#         row[start_key] = now
#         row[end_key] = now

#     elif old_status == "in_progress" and new_status == "done":
#         row[end_key] = now

#     elif old_status == "in_progress" and new_status == "pending":
#         row.pop(start_key, None)
#         row.pop(end_key, None)

#     elif old_status == "done" and new_status == "in_progress":
#         row[start_key] = now
#         row.pop(end_key, None)

#     elif old_status == "done" and new_status == "pending":
#         row.pop(start_key, None)
#         row.pop(end_key, None)


def apply_interval_transition(meta_dict, old_status, new_status, start_key, end_key, now_chi):
    """
    Generic interval state machine.

    Active states   : in_progress, done
    Inactive states : pending, terminate
    """

    old = (old_status or "").lower()
    new = (new_status or "").lower()

    active_states = ("in_progress", "done")
    inactive_states = ("pending", "terminate")

    # --------------------------------------------------
    # 1️⃣ RESET: entering inactive state
    # --------------------------------------------------
    if new in inactive_states:
        meta_dict[start_key] = ""
        meta_dict[end_key] = ""
        return

    # --------------------------------------------------
    # 2️⃣ START: entering in_progress from inactive
    # --------------------------------------------------
    if new == "in_progress" and old in inactive_states:
        meta_dict[start_key] = now_chi
        meta_dict[end_key] = ""
        return

    # --------------------------------------------------
    # 3️⃣ COMPLETE: entering done
    # --------------------------------------------------
    if new == "done" and old != "done":

        # If start was missing (terminate → done or pending → done)
        if not meta_dict.get(start_key):
            meta_dict[start_key] = now_chi

        meta_dict[end_key] = now_chi
        return
