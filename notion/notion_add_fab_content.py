import json
import os
import sys
from .pkg.eeroq_notion import Page, Database, Block, table, toggle_blocks
from notion_client import Client as NotionClient

# import any helper you already use in the notebook logic


def add_fab_content(
    *,
    notion_token: str,
    page_url: str,
    num_chips: int,
    payload: dict,
    mode: str = "all",
):
    notion = NotionClient(auth=notion_token)  
    db_page = Page("link to notion db page", page_url)
    mode = (mode or "all").strip().lower()

    fabdata_db = []
    created_page_ids = []
    fabdata_db_url = ['https://www.notion.so/eeroq/4a3b49a78ddf40b5bd7e5d299d61b21d?v=ba924f789e90485fb33862bc39252e60',
     'https://www.notion.so/eeroq/3be71cbfccff40b986c0d5e112339d84?v=80f4ede71808417cbe0b29ae257b3548',
     'https://www.notion.so/eeroq/1783a2c724ad4a7f9d8e8d8b2cc258ba?v=4b73e0ffb48145c685ff4ca717e12694',
     'https://www.notion.so/eeroq/c8431c33e4a04d32a3dfdd0524c36856?v=b21a8edd59b74bf99580213abc16cc0b',
     'https://www.notion.so/eeroq/eaa7767f48c6493ea266661c8626ccdc?v=8d10e6243e154bea92c022ae5d1f153a',
     'https://www.notion.so/eeroq/1ba410f6a1834fada426149ede3a5dd1?v=ab73c4fdd7144fd6be525f7f7eaa8e2a',
     'https://www.notion.so/eeroq/e5d8409c22264fc2bc81ac6a6e57a2a7?v=44dda9b9042a42d18ffb2a446c8693c3',
     'https://www.notion.so/eeroq/7fd84100628147e19194aa1eb87708b1?v=b8930e40f75c4297b67ae51abd0f9455',
     'https://www.notion.so/eeroq/57abf492052c48e2bd9c6089f140f97a?v=bd73509e705745ada5d82d9b2fa54ce8']


    for url in fabdata_db_url:
        db = Database(url=url)
        fabdata_db.append(db)
    

    #### Update fabdata 9 databases
    ####

    # -------------------------------------------------
    # Required properties (must be present)
    # -------------------------------------------------
    lot_id = (payload.get("lot_id") or "").strip()
    name = (payload.get("name") or "").strip()
    fabin = (payload.get("fabin") or "").strip()
    dev_type = (payload.get("type") or "").strip()
    top_callout = (payload.get("top_callout") or "").strip()


    # Hard stop if any required property is missing
    missing = []
    if not lot_id:
        missing.append("Lot ID")
    if not name:
        missing.append("Name")
    if not fabin:
        missing.append("FABIN")
    if not dev_type:
        missing.append("Type")

    if missing:
        return {
            "error": "Missing required properties for Fab content creation",
            "missing": missing,
        }

    new_properties = {
        "Lot ID": lot_id,
        "Name": name,
        "FABIN": fabin,
        "Type": dev_type,
    }


    if mode in ("all", "setup"):
        # create 9 DB pages + add properties

        db_page_list = []
        for i in range(len(fabdata_db_url)):
            new_db_page = Page()
            db_page_list.append(new_db_page)

        for i, db in enumerate(fabdata_db):
            db_page_list[i].add_properties(new_properties)
            db.add_page(db_page_list[i])

        # -------------------------------------------------
        # Collect created Fab child page IDs (WRITE-ONCE FACT)
        # -------------------------------------------------
        for p in db_page_list:
            if p and getattr(p, "id", None):
                created_page_ids.append(p.id)



        ### create db page content
        ###
        n_databases = len(fabdata_db_url)
        sync_block_list = [Block(sync=True) for i in range(n_databases)]

        sync_block_list[0].heading("History", header_type=2).divider().toggle_blocks("data").space()
        sync_block_list[1].heading("Schematic", header_type=2).divider().toggle_blocks("chip").toggle_blocks("wafer").space()
        sync_block_list[2].heading("Process", header_type=2).divider().toggle_blocks("flow").space()
        sync_block_list[3].heading("Profile", header_type=2).divider().toggle_blocks("cross-section").toggle_blocks("data").space()
        sync_block_list[4].heading("Design", header_type=2).divider().toggle_blocks("chip file").toggle_blocks("wafer file").space()
        sync_block_list[5].heading("Microscope", header_type=2).divider().toggle_blocks("wafer").toggle_blocks("chip").space()
        sync_block_list[6].heading("SEM", header_type=2).divider().toggle_blocks("wafer").toggle_blocks("chip").space()

        # sync_block_list[7].heading("Wire bond", header_type=2).divider().toggle_blocks(main="C01", 
        #                                                                                subs = ["PCB GPO connection","Resistance","Image"], sub_toggle=True).space()

        sync_block_list[7].heading("Wire bond", header_type=2).divider()
        for i in range(num_chips):
            sync_block_list[7].toggle_blocks(main="C0"+str(i+1), subs = ["PCB GPO connection","Resistance","Image"], sub_toggle=True)
        sync_block_list[7].space()

        sync_block_list[8].heading("Report", header_type=2).divider().toggle_blocks("file").space()

        # top_block = Block().callout("Patterning process : L0 Alignment marker, L1 Si trench (top-metal covered), L2 bottom-metal, L3 top-metal,  L4 airbridge hole, L5 airbridge bar")
        # top_block.space()

        # -----------------------------------------
        # Top callout (payload-driven, fallback-safe)
        # -----------------------------------------
        if not top_callout:
            top_callout = "Patterning process : L0 Alignment marker, L1 Si trench (top-metal covered), L2 bottom-metal, L3 top-metal,  L4 airbridge hole, L5 airbridge bar"

        top_block = Block().callout(top_callout)
        top_block.space()


            
    if mode in ("all", "main"):
        # add top_block + sync blocks to main page

        #### add content to main device db page
        ####
        db_page.add_block(top_block)
        for s_block in sync_block_list:
            db_page.add_block(s_block)
        print("main page content is created!", file=sys.stderr, flush=True)
        

    if mode in ("all", "fill"):
        # append tables/toggles to profile/microscope/sem/wirebond etc.

        #### add content to fabdata db page
        ####

        fabdata_db_label = ["History", "Schematic", "Process", "Profile", "Design", "Microscope", "SEM", "Wirebond", "Report"]

        fabdata_db_content = []
        for i, s_block in enumerate(sync_block_list):
            block = db_page_list[i].copy_sync_block(s_block)
            fabdata_db_content.append(block)
            print(f"{fabdata_db_label[i]} page content is created!", file=sys.stderr, flush=True)


        # import pandas
        # from pkg.eeroq_notion import *
        ####History db page
        ####
        history = fabdata_db_content[0]

        # csv = pandas.read_csv("../Fab_history_TiN.csv")
        # header = header = csv.columns.tolist()
        # cell = csv.iloc[:].to_numpy()

        # table_code = table(header = header, content = cell)['code']
        notion.blocks.children.append(block_id = history.id_list[2]['child2'], children = [])

        ####Profile db page
        ####
        profile = fabdata_db_content[3]
        table_code = table(header = ["Label", "t1", "t2", "t3", "d1", "d2", "h"], content = [["Thickness", "", "", "", "", "", ""]], 
                           has_row_header = True)['code']
        notion.blocks.children.append(block_id = profile.id_list[3]['child3'], children = [table_code])

        ####Microscope db page
        ####
        microscope = fabdata_db_content[5]
        toggle_list = []
        for i in range(num_chips):
            toggle_list.append(toggle_blocks('C0'+str(i+1))['code'])
        notion.blocks.children.append(block_id = microscope.id_list[3]['child3'], children = toggle_list)

        ####SEM db page
        ####
        sem = fabdata_db_content[6]
        toggle_list = []
        for i in range(num_chips):
            toggle_list.append(toggle_blocks('C0'+str(i+1))['code'])
        notion.blocks.children.append(block_id = sem.id_list[3]['child3'], children = toggle_list)

        ####Wirebond db page
        ####
        wirebond_block = fabdata_db_content[7]
        toggle_id = []
        child_list = ["child"+str(i+2) for i in range(num_chips)]
        for child_id in wirebond_block.id_list:
            for k, v in child_id.items():
                if k in child_list:
                    toggle_id.append(v) 

        sub_toggle_id = []
        for t_id in toggle_id:
            sub_toggle_id.append(notion.blocks.children.list(t_id)['results'][1]['id'])

        table_code = table(header = ["Connection", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16"], 
                           content = [["R (kOhm)", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]], has_row_header = True)['code']

        for st_id in sub_toggle_id:
            notion.blocks.children.append(block_id = st_id, children = [table_code])

        # return {"success": True}
        return {
            "success": True,
            "fab_child_page_ids": created_page_ids,
        }




def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing JSON payload"}))
        sys.exit(2)

    payload = json.loads(sys.argv[1])

    # (optional) only if you actually use mode later
    mode = (payload.get("mode") or "all").strip().lower()

    notion_token = os.environ.get("NOTION_TOKEN", "").strip()
    if not notion_token:
        print(json.dumps({"error": "NOTION_TOKEN env var missing"}))
        sys.exit(2)

    page_url = (payload.get("page_url") or "").strip()
    if not page_url:
        print(json.dumps({"error": "Missing page_url"}))
        sys.exit(2)

    num_chips = payload.get("num_chips", 0)
    try:
        num_chips = int(num_chips)
    except Exception:
        num_chips = 0

    out = add_fab_content(
        notion_token=notion_token,
        page_url=page_url,
        num_chips=num_chips,
        payload=payload,
        mode=mode,
    )

    print(json.dumps(out))


if __name__ == "__main__":
    main()
