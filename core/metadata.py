def normalize_meta(meta):
    """
    Ensure metadata is always a list of:
    { "key": ..., "value": ... }
    """
    out = []
    for item in meta:
        if isinstance(item, dict) and "key" in item and "value" in item:
            out.append({"key": item["key"], "value": item["value"]})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            k, v = item
            out.append({"key": k, "value": v})
    return out



def ensure_kv_rows(meta_list, ordered_keys):
    """
    Ensure the given key/value rows exist in meta_list, and stay in the specified order.
    If missing, insert with empty value.
    """
    meta_list = normalize_meta(meta_list)

    def find_idx(k):
        for i, row in enumerate(meta_list):
            if row.get("key", "").strip().lower() == k.strip().lower():
                return i
        return None

    # Ensure in order, inserting at the right positions
    insert_pos = 0
    for k in ordered_keys:
        idx = find_idx(k)
        if idx is None:
            meta_list.insert(insert_pos, {"key": k, "value": ""})
            insert_pos += 1
        else:
            # Move existing row to the correct position to lock ordering
            row = meta_list.pop(idx)
            meta_list.insert(insert_pos, row)
            insert_pos += 1

    return meta_list




def build_package_chip_meta(layers, old_chip_meta):
    chip_meta = {}

    package_layer = next(
        (l for l in layers if l.get("layer_name") == "Package"),
        None
    )
    if not package_layer:
        return chip_meta

    for sub in package_layer.get("substeps", []):
        chip_uid = sub.get("chip_uid")
        if not chip_uid:
            continue

        prev = old_chip_meta.get(chip_uid, {})

        chip_meta[chip_uid] = {
            "pcb_pic":   prev.get("pcb_pic", ""),
            "pcb_ready": prev.get("pcb_ready", ""),
            "pcb_type":  prev.get("pcb_type", ""),
            "bond_pic":  prev.get("bond_pic", ""),
            "bond_date": prev.get("bond_date", ""),
            "notion":    prev.get("notion", ""),
            "notes":     prev.get("notes", ""),

            # ✅ MINIMAL: preserve delivery fields too
            "delivery":      prev.get("delivery", ""),
            "delivery_time": prev.get("delivery_time", ""),
        }

    return chip_meta





def build_measure_fridge_meta(layers, old_measure_meta):
    """
    Build fridge-centric Measurement metadata from flow editor layers.
    """
    fridge_meta = {}

    if not isinstance(old_measure_meta, dict):
        old_measure_meta = {}

    measure_layer = next(
        (l for l in layers if l.get("layer_name") == "Measurement"),
        None
    )
    if not measure_layer:
        return fridge_meta

    for sub in measure_layer.get("substeps", []):
        fridge_uid = sub.get("fridge_uid")
        if not fridge_uid:
            continue

        prev = old_measure_meta.get(fridge_uid, {})
        
        fridge_meta[fridge_uid] = {
            "owner":     prev.get("owner", ""),
            "chip_uid":  prev.get("chip_uid", ""),
            "cell_type": prev.get("cell_type", ""),
            "notion":    prev.get("notion", ""),
            "notion_page_id": prev.get("notion_page_id", ""),  # ✅ PATCH
            "notes":     prev.get("notes", ""),

            "cooldown_start": prev.get("cooldown_start", ""),
            "cooldown_end":   prev.get("cooldown_end", ""),
            "measure_start":  prev.get("measure_start", ""),
            "measure_end":    prev.get("measure_end", ""),
            "warmup_start":   prev.get("warmup_start", ""),
            "warmup_end":     prev.get("warmup_end", ""),
        }


    return fridge_meta



def get_package_chips_safe(update_meta):
    """
    Return stored package chip metadata safely.
    """
    pkg = update_meta.get("package")
    if isinstance(pkg, dict):
        return pkg.get("chips", {})
    return {}




from collections import OrderedDict

def get_package_chips(layers):
    chip_map = OrderedDict()

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


def get_measure_fridges(layers):
    fridge_map = OrderedDict()

    for layer in layers:
        if layer.get("layer_name") != "Measurement":
            continue

        for sub in layer.get("substeps", []):
            fridge_uid = sub.get("fridge_uid")
            if not fridge_uid:
                continue


            label = sub.get("label") or sub.get("name") or "Unknown"
            fridge_map[fridge_uid] = label

    return fridge_map

