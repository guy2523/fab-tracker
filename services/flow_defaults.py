
import copy

# ------------------------------------------------------------
# Default Flow (Layers / Substeps / Chips)
# ------------------------------------------------------------
DEFAULT_FLOW = [
    {
        "layer_name": "Design",
        "icon": "🎨",
        "substeps": [
            {
                "name": "Design",
                "chips": [
                    {"name": "Spec"},
                    {"name": "Function"},
                    {"name": "DRC"},
                    {"name": "Finalize"},
                ],
            }
        ],
    },
    {
        "layer_name": "Fabrication",
        "icon": "⚡",
        "substeps": [
            {
                "name": "Fab",
                "chips": [
                    {"name": "Marker"},
                    {"name": "Trench"},
                    {"name": "Top TiN"},
                    {"name": "Bot Nb"},
                    {"name": "Bot Co"},
                    {"name": "Airbridge"},
                    {"name": "Dicing"},
                ],
            },
        ],
    },
  
    {
        "layer_name": "Package",
        "icon": "𓇲",
        "substeps": [
            {
                "chip_uid": "chip_default_c01",
                "label": "C01",
                "chips": [
                    {"name": "PCB"},
                    {"name": "Bonding"},
                    {
                        "name": "Delivery",
                        "type": "delivery",
                        "status": "pending",
                    },
                ],
            },
        ],
    },

    {
        "layer_name": "Measurement",
        "icon": "📈",
        "substeps": [
            {
                "fridge_uid": "fridge_default_iceoxford",
                "label": "ICEOxford",
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
            },
            {   
                "fridge_uid": "fridge_default_bulefors",
                "label": "Bluefors",
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
            },
        ],
    },
]


EMPTY_FLOW = [
    {"layer_name": "Design",       "substeps": []},
    {"layer_name": "Fabrication",  "substeps": []},
    {"layer_name": "Package",      "substeps": []},
    {"layer_name": "Measurement",  "substeps": []},
]



def get_default_layer(layer_name):
    for layer in DEFAULT_FLOW:
        if layer["layer_name"] == layer_name:
            return copy.deepcopy(layer)
    return None