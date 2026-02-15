from firebase_client import (
    firestore_set,
    firestore_list,
    firestore_to_python,   # needed by load_layer_presets_once
)



def load_layer_presets_once(session_state, id_token, default_flow):

    # Only load presets from Firestore once per session
    if session_state.get("layer_presets_loaded"):
        return

    # Ensure container exists
    session_state.setdefault("layer_presets", {})

    # 1) Load entire collection
    all_docs = firestore_list("layer_presets", id_token)

    preset_lookup = {}
    for doc in all_docs.get("documents", []):
        full_name = doc["name"]
        doc_id = full_name.split("/")[-1]  # e.g. "Design_preset1"

        fields = doc.get("fields", {})
        if "substeps" in fields:
            preset_lookup[doc_id] = firestore_to_python(fields["substeps"])

    # 2) Convert lookup into your session_state structure
    for base_layer in default_flow:  # <-- use the argument, not DEFAULT_FLOW
        layer_name = base_layer["layer_name"]
        session_state["layer_presets"].setdefault(layer_name, {})

        for i in range(1, 6):  # preset1 → preset5
            doc_key = f"{layer_name}_preset{i}"
            if doc_key in preset_lookup:
                slot_idx = str(i - 1)  # "0".."4"
                session_state["layer_presets"][layer_name][slot_idx] = preset_lookup[doc_key]

    session_state["layer_presets_loaded"] = True




def save_layer_preset(layer_name, slot_idx, substeps, id_token):
    data = {"substeps": substeps}

    # slot_idx is "0".."4" or 0..4
    i = int(slot_idx) + 1
    doc_id = f"{layer_name}_preset{i}"

    return firestore_set("layer_presets", doc_id, data, id_token=id_token)
