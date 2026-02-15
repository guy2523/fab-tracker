from services.timestamps import (apply_chip_status_transition, apply_package_auto_dates, apply_measurement_auto_dates)

from datetime import datetime

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def apply_storage_auto_state(
    *,
    layer_name,
    chip_ref,
    chip_name,
    chip_uid,
    old_status,
    new_status,
    update_meta,
):
    layer = (layer_name or "").strip().lower()
    chip_type = (chip_ref.get("type") or "").strip().lower()
    chip_name_norm = (chip_name or "").strip().lower()
    status = (new_status or "").strip().lower()

    def is_store_state(s: str) -> bool:
        return s.startswith("store#")

    def is_delivery_state(s: str) -> bool:
        return s.startswith("delivery#")

    # -----------------------------
    # PACKAGE → per-chip DELIVERY (chip-centric)
    # -----------------------------
    if layer == "package":
        # Identify delivery chip (prefer type; fallback to name)
        is_delivery_chip = (
            chip_type == "delivery"
            or chip_name_norm == "delivery"
            or chip_name_norm.startswith("delivery")
        )

        if not is_delivery_chip:
            return

        chips = (
            update_meta
            .setdefault("package", {})
            .setdefault("chips", {})
        )
        chip_meta = chips.setdefault(chip_uid, {})

        # Always store the current delivery state string (e.g., "delivery#2" or "")
        if is_delivery_state(status):
            chip_meta["delivery"] = status
        else:
            # If someone sets it to pending (or anything else), clear the delivery label
            chip_meta["delivery"] = ""

        # Auto timestamp logic (write-once, clear on revert)
        if status == "pending" or status == "":
            chip_meta["delivery_time"] = ""
        else:
            # any non-pending status for this chip means "delivery started"
            if not chip_meta.get("delivery_time"):
                chip_meta["delivery_time"] = now_str()

        return

    # -----------------------------
    # MEASUREMENT → per-fridge STORAGE (fridge-centric)
    # -----------------------------
    if layer == "measurement":
        # Identify storage chip (prefer type; fallback to name)
        is_storage_chip = (
            chip_type == "storage"
            or chip_name_norm == "storage"
            or chip_name_norm.startswith("storage")
        )
        if not is_storage_chip:
            return

        fridges = (
            update_meta
            .setdefault("measure", {})
            .setdefault("fridges", {})
        )

        fridge_uid = chip_uid  # ✅ minimal: measurement passes fridge_uid through chip_uid
        fridge_meta = fridges.setdefault(fridge_uid, {})

        # Store current storage state string (e.g., "store#2" or "")
        if is_store_state(status):
            fridge_meta["storage"] = status
        else:
            fridge_meta["storage"] = ""

        old_s = (old_status or "").strip().lower()

        if not is_store_state(old_s) and is_store_state(status):
            if not fridge_meta.get("storage_time"):
                fridge_meta["storage_time"] = now_str()

        # Transition OUT of store state
        elif is_store_state(old_s) and not is_store_state(status):
            fridge_meta["storage_time"] = ""


        return



def handle_chip_status_change(
    *,
    chip_ref,
    old_status,
    new_status,
    layer_name,
    chip_name,
    chip_uid,
    update_meta,
    loaded_run_doc_id,
    id_token,
    now_chi,
):
    apply_chip_status_transition(
        chip_ref,
        old_status,
        new_status,
        now_chi,
    )

    apply_package_auto_dates(
        layer_name,
        chip_name,
        chip_uid,
        old_status,
        new_status,
        update_meta,
        loaded_run_doc_id,
        id_token,
        now_chi,
    )

    # --------------------------------------------------
    # 🧊 Measurement fridge initialization (CRITICAL)
    # Prevent status inheritance when a new fridge is added
    # --------------------------------------------------
    if (layer_name or "").strip().lower() == "measurement":
        fridges = (
            update_meta
            .setdefault("measure", {})
            .setdefault("fridges", {})
        )

        # If this fridge_uid is new, initialize clean metadata
        if chip_uid not in fridges:
            fridges[chip_uid] = {
                "cooldown_start": "",
                "cooldown_end": "",
                "measure_start": "",
                "measure_end": "",
                "warmup_start": "",
                "warmup_end": "",
                "storage": "",
                "storage_time": "",
                "notion": "",
                "notion_page_id": "",
            }


    apply_measurement_auto_dates(
    layer_name,
    chip_name,
    chip_uid,
    old_status,
    new_status,
    update_meta,
    now_chi,
    )

        # 🔒 storage → auto-derived metadata
    apply_storage_auto_state(
        layer_name=layer_name,
        chip_ref=chip_ref,
        chip_name=chip_name,
        chip_uid=chip_uid,
        old_status=old_status,
        new_status=new_status,
        update_meta=update_meta,
    )

