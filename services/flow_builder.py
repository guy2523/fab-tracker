import copy
import uuid

def ensure_ids(flow):
    for layer in flow:
        for sub in layer["substeps"]:
            if "id" not in sub:
                sub["id"] = str(uuid.uuid4())


def ensure_chip_ids(flow):
    for layer in flow:
        # 🔒 Only Package layer defines chip identity
        if layer.get("layer_name") != "Package":
            continue

        for sub in layer.get("substeps", []):
            # 🔑 THIS IS THE CRITICAL LINE
            if "chip_uid" not in sub:
                sub["chip_uid"] = f"chip_{uuid.uuid4().hex[:8]}"

            # Optional but recommended
            if "label" not in sub:
                sub["label"] = sub.get("name", "C??")



def ensure_fridge_ids(flow):
    for layer in flow:
        # 🔒 Only Measurement layer defines fridge identity
        if layer.get("layer_name") != "Measurement":
            continue

        for sub in layer.get("substeps", []):
            if "fridge_uid" not in sub:
                sub["fridge_uid"] = f"fridge_{uuid.uuid4().hex[:8]}"

            # Optional but recommended (mirrors Package)
            if "label" not in sub:
                sub["label"] = sub.get("name", "Fridge??")


def ensure_flow_ids(layers):
    """
    Ensure all identity invariants for a flow:
    - substep UI IDs
    - package chip_uid and label

    Mutates layers in-place
    """
    ensure_ids(layers)
    ensure_chip_ids(layers)
    ensure_fridge_ids(layers)




def firestore_fields_to_layers(fields):
    """
    Convert Firestore run fields -> Python layers structure
    """

    steps_raw = fields["steps"]["arrayValue"]["values"]
    layers_py = []

    for layer in steps_raw:
        lf = layer["mapValue"]["fields"]

        substeps_py = []
        for sv in lf["substeps"]["arrayValue"]["values"]:
            sf = sv["mapValue"]["fields"]

            chips = []
            for ch in sf["chips"]["arrayValue"]["values"]:
                cf = ch["mapValue"]["fields"]
                chips.append({
                    "name": cf["name"]["stringValue"],
                    "status": cf["status"]["stringValue"],
                })


            sub_name = (
                sf.get("label", {}).get("stringValue")
                or sf.get("name", {}).get("stringValue")
                or "Unknown"
            )

            substeps_py.append({
                "name": sub_name,                      # ← unified display name
                "chip_uid": sf.get("chip_uid", {}).get("stringValue"),
                "label": sub_name,                     # ← always consistent
                "chips": chips,
            })

        layers_py.append({
            "layer_name": lf["layer_name"]["stringValue"],
            "progress": int(lf["progress"]["integerValue"]),
            "substeps": substeps_py,
        })

    ensure_flow_ids(layers_py)

    return layers_py


def build_default_flow(default_flow):
    """
    Build a fresh editable flow from DEFAULT_FLOW.
    """

    flow = copy.deepcopy(default_flow)
    ensure_flow_ids(flow)
    return flow
