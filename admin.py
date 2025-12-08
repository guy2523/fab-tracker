
# admin.py
import streamlit as st
from firebase_client import auth, firestore_set, firestore_get


#### helper function


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




st.set_page_config(page_title="Fab Tracker - Admin", page_icon="🛠", layout="wide")

# ====================================================
# 1. LOGIN PAGE
# ====================================================
if "user" not in st.session_state:
    st.header("🔐 Admin Login")

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            st.session_state["user"] = user
            st.success("Login successful!")
            st.rerun()
        except Exception as e:
            st.error(f"Login failed: {e}")
    st.stop()

user = st.session_state["user"]
id_token = user["idToken"]
user_email = user["email"]

st.sidebar.success("Logged in as: " + user_email)
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()

# ====================================================
# 2. CREATE FABRICATION RUN
# ====================================================
st.header("🆕 Create Run")

with st.form("create_run_form"):
    col1, col2 = st.columns(2)

    with col1:
        scol1, scol2 = st.columns(2)

        with scol1:
            run_no = st.text_input("Run No. (e.g., 001)")
            created_date = st.text_input("Created (YYYY-MM-DD)")

        with scol2:
            device_name = st.text_input("Device Name")
            creator = st.text_input("Creator", value=user_email)

    with col2:

        st.markdown("<div>ℹ️ Detailed info</div>", unsafe_allow_html=True)
        # st.markdown("Metadata (optional)")


        # ----------- DESIGN METADATA ------------
        # st.subheader("Design Metadata")
        with st.expander("🎨 Design", expanded=False):
            col1, col2, col3= st.columns(3)
            with col1:
                name       = st.text_input("Design name", "")
                completed  = st.text_input("Completion date (YYYY-MM-DD)", "")
                file_design  = st.text_input("Attach file", "")

            with col2:
                creator    = st.text_input("Who creates?", "")
                spec       = st.text_input("Specification", "")
                notion_design     = st.text_input("Notion link (design)", "")

            with col3:
                verifier   = st.text_input("Who verifies design?", "")
                chip_size  = st.text_input("Chip size", "")
            

            notes_design      = st.text_area("Notes (design)", "")

            design_meta = [
                {"key":"Name",            "value":name},
                {"key":"Creator",         "value":creator},
                {"key": "Verifier",       "value":verifier},
                {"key":"Completed",       "value":completed},
                {"key":"Spec",            "value":spec},
                {"key":"Chip size",       "value":chip_size},
                {"key":"File",            "value":file_design},
                {"key":"Notion",          "value":notion_design},
                {"key":"Notes",           "value":notes_design},

            ]

        # ----------- FAB METADATA ------------
        with st.expander("⚡ Fab", expanded=False):
            col1, col2, col3= st.columns(3)

            with col1:
                lotid       = st.text_input("Lot ID", "")
                fabin       = st.text_input("Fabin date (YYYY-MM-DD)", "")
                substrate   = st.text_input("Substrate", "")

            with col2:
                pic_fab     = st.text_input("Person in-charege (fab)", "")
                fabout      = st.text_input("Fabout date (YYYY-MM-DD)", "")
                notion_fab  = st.text_input("Notion link (fab)", "")

            with col3:
                type_       = st.text_input("Device type (e.g. Resonator)", "")
                process     = st.text_input("Process (e.g. Top-down)", "")

            notes_fab   = st.text_area("Notes (fab)", "")



            fab_meta = [
                {"key":"Lotid",         "value":lotid},
                {"key":"PIC*",          "value":pic_fab},
                {"key":"Type",          "value":type_},
                {"key":"Fabin",         "value":fabin},
                {"key":"Fabout",        "value":fabout},
                {"key":"Process",       "value":process},                
                {"key":"Substrate",     "value":substrate},
                {"key":"Notion",        "value":notion_fab},
                {"key":"Notes",         "value":notes_fab},
                # {"key":"Chip size",     "value":st.text_input("Fab - Chip size", "")},
                # {"key":"# of chips",    "value":st.text_input("Fab - # of chips", "")},
                # {"key":"Bonded chip",   "value":st.text_input("Fab - Bonded chip", "")},
            ]

        # ----------- PACKAGE METADATA ------------
        with st.expander("𓇲 Package", expanded=False):
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                pic_dice         = st.text_input("Person in-charge (dicing)", "")
                pic_pcb          = st.text_input("Person in-charge (pcb)", "")
                pic_bond         = st.text_input("Person in-charge (bond)", "")

            with col2:
                dice_date        = st.text_input("Dicing (YYYY-MM-DD)", "")
                pcb_type         = st.text_input("PCB type", "")
                bond_date        = st.text_input("Bonding (YYYY-MM-DD)", "")

            with col3:
                chip_size_pkg    = st.text_input("Chip size (dicing)", "")
                pcb_date         = st.text_input("PCB ready (YYYY-MM-DD)")
                bonded_chips     = st.text_area("Bonded chips")

            with col4:
                n_chips          = st.text_input("Chip Qty", "")
                pcb_map          = st.text_input("PCB map")
                notion_pkg       = st.text_input("Notion link (package)")


            notes_pkg        = st.text_area("Notes (package)")


            package_meta = [
                {"key":"Dicing PIC*",       "value":pic_dice},
                {"key":"Dicing date",       "value":dice_date},
                {"key":"Chip size",         "value":chip_size_pkg},
                {"key":"# of chips",        "value":n_chips},
                # {"key":"",                  "value":""},
                # {"key":"",                  "value":""},
                {"key":"PCB PIC*",          "value":pic_pcb},
                {"key":"PCB type",          "value":pcb_type},
                {"key":"PCB ready",         "value":pcb_date},
                {"key":"PCB map",           "value":pcb_map},
                # {"key":"",                  "value":""},
                # {"key":"",                  "value":""},
                {"key":"Bonding PIC*",      "value":pic_bond},
                {"key":"Bonding date",      "value":bond_date},
                {"key":"Bonded chips",      "value":bonded_chips},
                {"key":"Notion",            "value":notion_pkg},
                {"key":"Notes",             "value":notes_pkg},
            ]

        # ----------- MEA   SUREMENT METADATA ------------
        with st.expander("📈 Measurement", expanded=False):

            col1, col2 = st.columns(2)

            with col1:
                fridge           = st.text_input("Fridge", "")
                chip_id          = st.text_input("Chip id", "")
                cooldown         = st.text_input("Cooldonw start (YYYY-MM-DD)", "")
                measure_end      = st.text_input("Measurement end (YYYY-MM-DD)", "")
                notion_measure   = st.text_input("Notion link (measure)")


            with col2:
                pic_measure      = st.text_input("Person in-charge (measurement)", "")
                cell_type          = st.text_input("Cell type", "")
                measure_start    = st.text_input("Measurement start (YYYY-MM-DD)", "")
                warmup_start       = st.text_input("Warmup start (YYYY-MM-DD)", "")

            notes_measure         = st.text_area("Notes (measure)")


            measure_meta = [
                {"key":"Fridge",               "value":fridge},
                {"key":"PIC*",                 "value":pic_measure},
                {"key":"Chip_id",              "value":chip_id},
                {"key":"Cell type",            "value":cell_type},
                {"key":"Cooldown start",       "value":cooldown},
                {"key":"Measurement start",    "value":measure_start},
                {"key":"Measurement end",      "value":measure_end},
                {"key":"Warmup start",         "value":warmup_start},
                {"key":"Notion",               "value":notion_measure},
                {"key":"Notes",                "value":notes_measure},
            ]


    # ---------- CLEAN CHIPS-ENABLED LAYER FORMAT ----------
    design = {
        "layer_name": "Design",
        "progress": 0,
        "substeps": [
            {
                "name": "Design",
                "chips": [
                    {"name": "Spec", "status": "pending"},
                    {"name": "Function", "status": "pending"},
                    {"name": "DRC", "status": "pending"},
                    {"name": "Finalize", "status": "pending"},
                ]
            }
        ]
    }

    fab = {
        "layer_name": "Fabrication",
        "progress": 0,
        "substeps": [
            {"name": "Marker",
             "chips": [
                {"name": "Clean", "status": "pending"},
                {"name": "TiN depo", "status": "pending"},
                {"name": "Litho", "status": "pending"},
                {"name": "Etch", "status": "pending"},
                {"name": "Strip", "status": "pending"},
             ]
            },
            {"name": "Trench",
             "chips": [
                {"name": "Litho", "status": "pending"},
                {"name": "Etch", "status": "pending"},
                {"name": "Strip", "status": "pending"},
             ]
            },
            {"name": "Top metal",
             "chips": [
                {"name": "Litho", "status": "pending"},
                {"name": "Etch", "status": "pending"},
                {"name": "Strip", "status": "pending"},
             ]
            },
            {
                "name": "Bot metal",
                "chips": [
                    {"name": "Litho", "status":"pending"},
                    {"name": "Nb deop", "status":"pending"},
                    {"name": "Strip", "status":"pending"},
                    {"name": "Litho", "status":"pending"},
                    {"name": "Co deop", "status":"pending"},
                    {"name": "Strip", "status":"pending"},
                ]
            },
            {
                "name": "Airbridge",
                "chips": [
                    {"name": "Litho", "status":"pending"},
                    {"name": "Reflow", "status":"pending"},
                    {"name": "Al depo", "status":"pending"},
                    {"name": "Litho", "status":"pending"},
                    {"name": "Etch", "status":"pending"},
                    {"name": "Strip", "status":"pending"},
                ]
            },
        ]
    }

    package = {
        "layer_name": "Package",
        "progress": 0,
        "substeps": [
            {"name": "Dicing",
             "chips": [
                {"name": "Dicing", "status": "pending"},
                {"name": "Sorting", "status": "pending"},
             ]
            },
            {"name": "PCB Assy",
             "chips": [
                {"name": "Preparation", "status": "pending"},
             ]
            },
            {"name": "Bonding",
             "chips": [
                {"name": "Chip on PCB", "status": "pending"},
                {"name": "Bonding", "status": "pending"},
             ]
            },
        ]
    }


    measurement = {
        "layer_name": "Measurement",
        "progress": 0,
        "substeps": [
            {"name": "ICEOxford",
             "chips": [
                {"name": "Electrical check", "status": "pending"},
                {"name": "Cooldown", "status": "pending"},
                {"name": "Measure", "status": "pending"},
                {"name": "Warmup", "status": "pending"},
             ]
            },
            {"name": "Bluefors",
             "chips": [
                {"name": "Electrical check", "status": "pending"},
                {"name": "Cooldown", "status": "pending"},
                {"name": "Measure", "status": "pending"},
                {"name": "Warmup", "status": "pending"},
             ]
            },
        ]
    }


    steps = [design, fab, package, measurement]

    submitted = st.form_submit_button("Create Run")

# ---------- CREATE RUN ----------
if submitted:
    data = {
        "run_no": run_no,
        "device_name": device_name,
        "creator": creator,
        "created_date": created_date,
        "steps": steps,            # ← RAW PYTHON LIST, NOT FIRESTORE-WRAPPED
        "metadata": {
            "design": design_meta,
            "fab": fab_meta,
            "package": package_meta,
            "measure": measure_meta,
        }
    }

    result = firestore_set(
        collection="runs",
        document=run_no,
        data=data,
        id_token=id_token,
    )

    st.success(f"Run '{run_no}' created successfully!")
    # st.json(result)


# ====================================================
# 3. UPDATE EXISTING RUN
# ====================================================
st.header("🔧 Update Run")

run_to_load = st.text_input("Enter Run ID to Load (e.g., run_001)")

if st.button("Load Run"):
    run_data = firestore_get("runs", run_to_load, id_token)

    if "fields" not in run_data:
        st.error("Run not found.")
    else:
        st.session_state["loaded_run"] = run_data
        st.session_state["loaded_run_no"] = run_to_load
        st.success("Run loaded!")

# ---------- SHOW RUN ----------
if "loaded_run" in st.session_state:

    run = st.session_state["loaded_run"]
    loaded_run_no = st.session_state["loaded_run_no"]

    fields = run["fields"]

    st.subheader(f"Editing Run: {loaded_run_no}")

    steps_raw = fields["steps"]["arrayValue"]["values"]

    # ----- Convert Firestore REST → Python dict -----
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
                    "status": cf["status"]["stringValue"]
                })

            substeps_py.append({
                "name": sf["name"]["stringValue"],
                "chips": chips,
            })

        layers_py.append({
            "layer_name": lf["layer_name"]["stringValue"],
            "progress": int(lf["progress"]["integerValue"]),
            "substeps": substeps_py,
        })


    # ----- UI for editing -----
    st.markdown(f"__Status__")
    icon_list = ["🎨","⚡","𓇲","📈"]
    for i, layer in enumerate(layers_py):

        with st.expander(f"{icon_list[i]} {layer['layer_name']}", expanded=False):

            # create 8 columns for substeps
            cols = st.columns(8)

            for j, sub in enumerate(layer["substeps"]):

                # pick which column to put this substep into
                target_col = cols[j % 8]

                with target_col:
                    st.markdown(f"###### {sub['name']}")

                    for k, ch in enumerate(sub["chips"]):
                        new_status = st.selectbox(
                            f"{ch['name']}",
                            ["pending", "in_progress", "done"],
                            index=["pending", "in_progress", "done"].index(ch["status"]),
                            key=f"{i}_{j}_{k}",
                        )

                        # update status
                        layer["substeps"][j]["chips"][k]["status"] = new_status


    # ----------- EDIT METADATA BLOCK (NEW LOCATION) -----------------
    st.markdown(f"")
    st.markdown(f"__Detailed Info__")

    meta_fields = fields.get("metadata", {}).get("mapValue", {}).get("fields", {})

    # Convert Firestore map → python lists of {key, value}
    design_meta_py  = firestore_to_python(meta_fields.get("design", []))
    fab_meta_py     = firestore_to_python(meta_fields.get("fab", []))
    package_meta_py = firestore_to_python(meta_fields.get("package", []))
    measure_meta_py = firestore_to_python(meta_fields.get("measure", []))

    def edit_metadata(title, meta_list, n_cols=3):
        with st.expander(title, expanded=False):
            cols = st.columns(n_cols)
            new_list = []

            for idx, item in enumerate(meta_list):

                key = item["key"].strip()
                if key == "":
                    continue

                val = item["value"]
                col = cols[idx % n_cols]

                with col:
                    widget_key = f"{title}_{key}_{idx}"

                    # --- Special rule for NOTES ---
                    if key.lower() == "notes":
                        new_val = st.text_area(
                            label=key,
                            value=val,
                            key=widget_key,
                            height=120,       # ensure multi-line
                            placeholder="Enter multi-line notes…"
                        )
                    else:
                        new_val = st.text_input(
                            label=key,
                            value=val,
                            key=widget_key
                        )

                new_list.append({"key": key, "value": new_val})

            return new_list

    design_meta_new  = edit_metadata("🎨 Design", design_meta_py)
    fab_meta_new     = edit_metadata("⚡ Fab", fab_meta_py)
    package_meta_new = edit_metadata("𓇲 Package", package_meta_py, n_cols=4)
    measure_meta_new = edit_metadata("📈 Measurement", measure_meta_py, n_cols=2)


    # ---- SAVE BUTTON ----
    if st.button("Save Changes"):

        # meta_raw = firestore_to_python(fields["metadata"])

        meta_raw = {
            "design": design_meta_new,
            "fab": fab_meta_new,
            "package": package_meta_new,
            "measure": measure_meta_new,
        }


        doc_data = {
            "run_no": fields["run_no"]["stringValue"],
            "device_name": fields["device_name"]["stringValue"],
            "created_date": fields["created_date"]["stringValue"],
            "creator": fields["creator"]["stringValue"],
            "steps": layers_py,
            "metadata": meta_raw,   # ←←← minimal required fix
        }

        firestore_set("runs", loaded_run_no, doc_data, id_token=id_token)
        st.success("Saved!")
        st.rerun()


