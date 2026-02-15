
import os
from notion_client import Client
from notion_client.helpers import get_id
import streamlit as st
notion = Client(auth=NOTION_TOKEN)
NOTION_TOKEN = st.secrets["notion"]["NOTION_TOKEN"]


color_list = [
    "blue",
    "brown",
    "default",
    "gray",
    "green",
    "pink",
    "purple",
    "red",
    "yellow",
]


def color_list(i):
    clist = ["blue", "brown", "default", "gray", "green", "pink", "purple", "red", "yellow"]
    n = len(clist)
    if i > n-1:
        i = i%n
    return clist[i]


def change_page_title(new_title: str, url: str):
    pg_info = get_page_info(url)
    properties_code = pg_info['properties_code']
    for v in properties_code.values():
        if 'title' in v:
            v['title'][0]['text']['content'] = new_title
    notion.pages.update(page_id = get_parent_id(url), properties = properties_code)




def change_database_title(new_title: str, url: str):
    title_code = [{'type': 'text', 'text': {'content': new_title, 'link': None}}]
    notion.databases.update(database_id = get_parent_id(url), title = title_code)




def get_block_code(url: str):
    block_req = []
    children = notion.blocks.children.list(get_parent_id(url))['results']
    # black_list = ['child_database', 'child_page', 'column_list', 'file', 'image', 'pdf']
    black_list = ['child_database', 'child_page', 'file', 'image', 'pdf']
    # nested_list = ['bulleted_list_item', 'numbered_list_item', 'to_do', 'toggle', 'table']
    nested_list = ['bulleted_list_item', 'numbered_list_item', 'to_do', 'toggle', 'table', 'column_list']


    for child in children:
        if child['type'] in black_list:
            print('{} copy is not supported with Python and try on Notion webpage'.format(child['type']))
            content = child['type']
            block_req.append({"paragraph": {"rich_text": [{"text": {"content": content + ' is not supported with Python and try on Notion webpage'},
                "annotations": {"bold": False,"italic": True, "strikethrough": True, "underline": False, "code": False, "color": 'red',}}]}})


        elif child['type'] == 'callout':
            child[child['type']].pop('icon')
            block_req.append({child['type']: child[child['type']]})


        elif child['type'] in nested_list:
            child_req = {child['type']: child[child['type']]}
            grand_child_req = []
            if child['has_children']:
                grand_children = notion.blocks.children.list(child['id'])['results']
                for grand_child in grand_children:
                    grand_child_req.append({grand_child['type']: grand_child[grand_child['type']]})
                
                    child_req[child['type']].update({'children': grand_child_req})
    
                    grand_grand_child_req = []
                    if grand_child['has_children']:
                        grand_grand_children = notion.blocks.children.list(grand_child['id'])['results']
                        for grand_grand_child in grand_grand_children:
                            grand_grand_child_req.append({grand_grand_child['type']: grand_grand_child[grand_grand_child['type']]})
        
                        grand_child[grand_child['type']].update({'children': grand_grand_child_req})
    
    
                        # grand_grand_grand_child_req = []
                        # if grand_grand_child['has_children']:
                        #     grand_grand_grand_children = notion.blocks.children.list(grand_grand_child['id'])['results']
                        #     for grand_grand_grand_child in grand_grand_grand_children:
                        #         grand_grand_grand_child_req.append({grand_grand_grand_child['type']: grand_grand_grand_child[grand_grand_grand_child['type']]})
        
                        #     grand_grand_child[grand_grand_child['type']].update({'children': grand_grand_grand_child_req})
                                                    
            else:
                child_req = {child['type']: child[child['type']]}
                    
            block_req.append(child_req)
        
        else:
            block_req.append({child['type']: child[child['type']]})

    return block_req

        


def get_block_info(url: str):
    id_list = []
    content_list = []
    code_list = []

    children = notion.blocks.children.list(get_parent_id(url))['results']
    black_list = ['file', 'image', 'pdf', 'video']
    black_list2 = ['child_database', 'child_page', 'link_preview', 'template']
    nested_list = ['bulleted_list_item', 'numbered_list_item', 'to_do', 'toggle', 'table', 'column_list']

    for i, child in enumerate(children):
        child_name = 'child'+str(i)
        id_list.append({child_name: child['id']})

    
    for i, child in enumerate(children):

        if child['type'] in black_list:

            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})

            if child[child['type']]['type'] == "external":
                code_list.append({child['type']: child[child['type']]})

            else:
                print('The copy of {} with upload is not supported with Python and try on Notion webpage'.format(child['type']))
                code_list.append({"paragraph": {"rich_text": [{"text": {"content": 'The copy of ' + child['type'] + ' with upload is not supported with Python and try on Notion webpage'},
                    "annotations": {"bold": False,"italic": True, "strikethrough": True, "underline": False, "code": False, "color": 'red',}}]}})


        elif child['type'] in black_list2:

            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})

            print('The copy of {} is not supported with Python and try on Notion webpage'.format(child['type']))
            code_list.append({"paragraph": {"rich_text": [{"text": {"content": "The copy of " + child['type'] + ' is not supported with Python and try on Notion webpage'},
                "annotations": {"bold": False,"italic": True, "strikethrough": True, "underline": False, "code": False, "color": 'red',}}]}})     


        elif child['type'] == 'callout':
            child[child['type']].pop('icon')
            
            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})
            
            code_list.append({child['type']: child[child['type']]})
            # content_list.append({child['type']: child[child['type']]})


        elif child['type'] == 'paragraph':
            code_list.append({child['type']: child[child['type']]})
            child_name = 'child'+str(i)

            try:
                content = child[child['type']]['rich_text'][0]['type']
            except:
                content = 'space'

            content_list.append({child_name : content})


        elif child['type'] in nested_list:
            child_req = {child['type']: child[child['type']]}
            
            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})
            
            grand_child_req = []
            if child['has_children']:
                grand_children = notion.blocks.children.list(child['id'])['results']
                for grand_child in grand_children:
                    grand_child_req.append({grand_child['type']: grand_child[grand_child['type']]})
                
                    child_req[child['type']].update({'children': grand_child_req})
    
                    grand_grand_child_req = []
                    if grand_child['has_children']:
                        grand_grand_children = notion.blocks.children.list(grand_child['id'])['results']
                        for grand_grand_child in grand_grand_children:
                            grand_grand_child_req.append({grand_grand_child['type']: grand_grand_child[grand_grand_child['type']]})
        
                        grand_child[grand_child['type']].update({'children': grand_grand_child_req})
    
    
                        # grand_grand_grand_child_req = []
                        # if grand_grand_child['has_children']:
                        #     grand_grand_grand_children = notion.blocks.children.list(grand_grand_child['id'])['results']
                        #     for grand_grand_grand_child in grand_grand_grand_children:
                        #         grand_grand_grand_child_req.append({grand_grand_grand_child['type']: grand_grand_grand_child[grand_grand_grand_child['type']]})
        
                        #     grand_grand_child[grand_grand_child['type']].update({'children': grand_grand_grand_child_req})
                                                    
            else:
                child_req = {child['type']: child[child['type']]}
                    
            code_list.append(child_req)
        
        else:
            code_list.append({child['type']: child[child['type']]})

            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})

    return id_list, content_list, code_list




def get_block_info_from_id(id: str):
    id_list = []
    content_list = []
    code_list = []

    children = notion.blocks.children.list(id)['results']
    black_list = ['file', 'image', 'pdf', 'video']
    black_list2 = ['child_database', 'child_page', 'link_preview', 'template']
    nested_list = ['bulleted_list_item', 'numbered_list_item', 'to_do', 'toggle', 'table', 'column_list']

    for i, child in enumerate(children):
        child_name = 'child'+str(i)
        id_list.append({child_name: child['id']})

    
    for i, child in enumerate(children):

        if child['type'] in black_list:

            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})

            if child[child['type']]['type'] == "external":
                code_list.append({child['type']: child[child['type']]})

            else:
                print('The copy of {} with upload is not supported with Python and try on Notion webpage'.format(child['type']))
                code_list.append({"paragraph": {"rich_text": [{"text": {"content": 'The copy of ' + child['type'] + ' with upload is not supported with Python and try on Notion webpage'},
                    "annotations": {"bold": False,"italic": True, "strikethrough": True, "underline": False, "code": False, "color": 'red',}}]}})


        elif child['type'] in black_list2:

            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})

            print('The copy of {} is not supported with Python and try on Notion webpage'.format(child['type']))
            code_list.append({"paragraph": {"rich_text": [{"text": {"content": "The copy of " + child['type'] + ' is not supported with Python and try on Notion webpage'},
                "annotations": {"bold": False,"italic": True, "strikethrough": True, "underline": False, "code": False, "color": 'red',}}]}})     


        elif child['type'] == 'callout':
            child[child['type']].pop('icon')
            
            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})
            
            code_list.append({child['type']: child[child['type']]})
            # content_list.append({child['type']: child[child['type']]})


        elif child['type'] == 'paragraph':
            code_list.append({child['type']: child[child['type']]})
            child_name = 'child'+str(i)

            try:
                content = child[child['type']]['rich_text'][0]['type']
            except:
                content = 'space'

            content_list.append({child_name : content})


        elif child['type'] in nested_list:
            child_req = {child['type']: child[child['type']]}
            
            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})
            
            grand_child_req = []
            if child['has_children']:
                grand_children = notion.blocks.children.list(child['id'])['results']
                for grand_child in grand_children:
                    grand_child_req.append({grand_child['type']: grand_child[grand_child['type']]})
                
                    child_req[child['type']].update({'children': grand_child_req})
    
                    grand_grand_child_req = []
                    if grand_child['has_children']:
                        grand_grand_children = notion.blocks.children.list(grand_child['id'])['results']
                        for grand_grand_child in grand_grand_children:
                            grand_grand_child_req.append({grand_grand_child['type']: grand_grand_child[grand_grand_child['type']]})
        
                        grand_child[grand_child['type']].update({'children': grand_grand_child_req})
    
    
                        # grand_grand_grand_child_req = []
                        # if grand_grand_child['has_children']:
                        #     grand_grand_grand_children = notion.blocks.children.list(grand_grand_child['id'])['results']
                        #     for grand_grand_grand_child in grand_grand_grand_children:
                        #         grand_grand_grand_child_req.append({grand_grand_grand_child['type']: grand_grand_grand_child[grand_grand_grand_child['type']]})
        
                        #     grand_grand_child[grand_grand_child['type']].update({'children': grand_grand_grand_child_req})
                                                    
            else:
                child_req = {child['type']: child[child['type']]}
                    
            code_list.append(child_req)
        
        else:
            code_list.append({child['type']: child[child['type']]})

            child_name = 'child'+str(i)
            content_list.append({child_name : child['type']})

    return id_list, content_list, code_list




def get_database_info(url: str)-> dict:
    database_id = get_parent_id(url)
    raw_info = notion.databases.retrieve(database_id = database_id)
    info = {}
    properties = []
    properties_code = raw_info['properties']
    # properties_code = get_properties_code_without_id(raw_info['properties'])

    # information except for properties

    for k, v in raw_info.items():

        if k == 'title':
            v = v[0]['text']['content']

        elif k == 'properties':
            break
        
        info.update({k: v})
    

    # properties

    for k, v in raw_info['properties'].items():
        properties_type = v['type']
        properties_name = k
        
        if properties_type == 'select':
            properties_option = v['select']['options']
            opt_list = [opt['name'] for opt in properties_option]                   
            properties.append({properties_type: {'name': properties_name, 'option': opt_list}})


        elif properties_type == 'multi_select':
            properties_option = v['multi_select']['options']
            opt_list = [opt['name'] for opt in properties_option]                   
            properties.append({properties_type: {'name': properties_name, 'option': opt_list}})


        elif properties_type == 'relation':
            rel_db_id = v[properties_type]['database_id']
            rel_type = v[properties_type]['type']   
            properties.append({properties_type: {'name': properties_name, 'rel_db_id': rel_db_id, 'type': rel_type}})


        elif properties_type == 'rollup':
            relation_property_name = v[properties_type]['relation_property_name']
            rollup_property_name = v[properties_type]['rollup_property_name']
            function =  v[properties_type]['function']
            properties.append({properties_type: {'name': properties_name, 'relation_property_name': relation_property_name,
             'rollup_property_name': rollup_property_name, 'function': function}})


        elif properties_type == 'rich_text':
            properties.append({'text': properties_name})


        else:
            properties.append({properties_type: properties_name})

    info.update({'properties': properties})
    info.update({'properties_code': properties_code})

    return info




def get_header_code(header_list: list) -> dict:

    code = {}

    for header in header_list:
    
        if 'checkbox' in header:
            code.update({header['checkbox']: {"checkbox": {}}}) 
    
        if 'created_by' in header:
            code.update({header['created_by']: {"created_by": {}}})
    
        if 'created_time' in header:
            code.update({header['created_time']: {"created_time": {}}})
    
        if 'date' in header:
            code.update({header['date']: {"date": {}}})
    
        if 'email' in header:
            code.update({header['email']: {"email": {}}})
        
        if 'file' in header:
            print("The Notion API does not support adding '{}' ('{}' type) column header to database. Try with Notion UI instead!".format(header['file'], 'file'))
        #     code.update({header['files']: {"files": {}}})
    
        if 'formula' in header:
            code.update({header['formula']: {"formula": {"expression": ""}}})
    
        if 'last_edited_by' in header:
            code.update({header['last_edited_by']: {"last_edited_by": {}}})

        if 'last_edited_time' in header:
            code.update({header['last_edited_time']: {"last_edited_time": {}}})
    
        if 'multi_select' in header:
            h = header['multi_select']
            select = [{"name": opt, "color": color_list(i)} for i, opt in enumerate(h['option'])]
            result =  {h["name"]: {"type": "multi_select", "multi_select": {"options": select}}}
            code.update(result)
    
        if 'number' in header:
            if isinstance(header['number'], list):
                result = {header['number'][0]: {"type": "number", "number": {"format": header['number'][1]}}}
    
            else:
                result = {header['number']: {"type": "number", "number": {"format": "number"}}}
            code.update(result)
    
        if 'people' in header:
            code.update({header['people']: {"people": {}}})
    
        if 'phone_number' in header:
            code.update({header['phone_number']: {"phone_number": {}}})
    
        if 'relation' in header:
            h = header['relation']
            result = {h['name']: {"relation": {"database_id": h['rel_db_id'], "type": h['type'], h['type']: {}}}}
            code.update(result)
    
        if 'rollup' in header:
            name = header['rollup']['name']
            relation_property_name = header['rollup']['relation_property_name']
            rollup_property_name = header['rollup']['rollup_property_name']
            function = header['rollup']['function']
    
            result = {name: {"rollup": {"rollup_property_name": rollup_property_name, "relation_property_name": relation_property_name, "function": function}}}
            code.update(result)
    
        if 'select' in header:
            h = header['select']
            select_list = [{"name": opt, "color": color_list(i)} for i, opt in enumerate(h['option'])]
            result =  {h["name"]: {"type": "select", "select": {"options": select_list}}}
            code.update(result)
    
        if 'status' in header:
            print("The Notion API does not support adding '{}' ('{}' type) column header to database. Try with Notion UI instead!".format(header['status'], 'status'))
    
    
        #     stat = {"options": [{"name": 'Not started', "color": "default"}, {"name": "In progress", "color": "blue"}, {"name": "Done", "color": "green"}], 
        #     "groups": [{"name": "To-do", "color": "gray"}, {"name": "In progress", "color": "blue"}, {"name": "Complete", "color": "green"}]}
        #     # result = {header['status']: {"type": "status", "status": stat}}
        #     result = {'Status': {"type": "select", "status": stat}}
        #     code.update(result)
    
        if 'title' in header:
            code.update({header['title']: {"title": {}}})
    
        if 'text' in header:
            code.update({header['text']: {"rich_text": {}}})
    
        if 'url' in header:
            code.update({header['url']: {"url": {}}})
    
    return code





def get_page_info(url: str)-> dict:
    page_id = get_parent_id(url)
    raw_info = notion.pages.retrieve(page_id)
    info = {}
    properties = {}

    properties_code = get_properties_code_without_id(raw_info['properties'])
    blank_page_properties_code = {'title': {'id': 'title', 'type': 'title', 'title': []}}

    # if it's a blank page
    if raw_info['properties'] == blank_page_properties_code:
        properties_code = blank_page_properties_code


    for k, v in raw_info.items():
        if k == 'created_by':
            v = v['object']

        elif k == 'last_edited_by':
            v = v['object']
       
        elif k == 'parent':
            v = v['type']

        # elif k == 'cover':
        #     if v != None:
        #         try:
        #             v = v['external']['url']

            
        elif k == 'properties':
            break
        
        info.update({k: v})


    for k, v in raw_info['properties'].items():
        for k1, v1 in v.items():

            if k1 in ['created_by', 'created_time', 'last_edited_by', 'last_edited_time', 'file', 'formula', 'people', 'relation', 'rollup', 'status']:
                pass

            if k1 == 'checkbox':
                try:
                    properties.update({k: v1})
                except:
                    pass

            if k1 == 'date':
                try:
                    properties.update({k: v1['start']})
                except:
                    pass

            if k1 == 'email':
                try:
                    properties.update({k: v1})
                except:
                    pass

            if k1 == 'multi_select':
                try:
                    properties.update({k: [v2['name'] for v2 in v1]})
                except:
                    pass


            if k1 == 'number':
                try:
                    properties.update({k: v1})
                except:
                    pass

            if k1 == 'phone_number':
                try:
                    properties.update({k: v1})
                except:
                    pass

            if k1 == 'rich_text':
                try:
                    properties.update({k: v1[0]['text']['content']})
                except:
                    pass

            if k1 == 'select':
                try:
                    properties.update({k: v1['name']})
                except:
                    pass

            if k1 == 'title':
                try:
                    properties.update({k: v1[0]['text']['content']})
                    page_name = v1[0]['text']['content']
                except:
                    page_name = ""
                    pass

            if k1 == 'url':
                try:
                    properties.update({k: v1})
                except:
                    pass

    info.update({'page_name': page_name})
    info.update({'properties': properties}) 
    info.update({'properties_code': properties_code})

    return info




def get_parent_id(url: str) -> str:
    """
    Get the ID of the parent page from the URL
    """
    input_url = url.strip()

    try:
        if input_url[:4] == "http":
            parent_id = get_id(input_url)
            # print(f"\nThe target page ID : {parent_id}")
        else:
            parent_id = input_url
        # notion.pages.retrieve(parent_id)
    except Exception as e:
        print(e)

    return parent_id




def get_properties_code(header_list: list, copy = False, **properties: dict) -> dict:

    code = {}
    htype_list = ['checkbox', 'created_by', 'created_time', 'date', 'email', 'file', 'formula', 'last_edited_by', 'last_edited_time', 'multi_select', 'number',
    'phone_number', 'people', 'relation', 'rollup', 'select', 'status', 'text', 'title', 'url']

    for htype in htype_list:

        for header in header_list:

            if htype in header:

                hvalue = header[htype]

                if isinstance(hvalue, dict):
                    hvalue = hvalue['name']


                if isinstance(hvalue, list):
                    hvalue = hvalue[0]

                if hvalue in properties:

                    if htype == 'checkbox':
                        code.update({header[htype]: {"type": "checkbox", "checkbox": properties[header[htype]]}})


                    if htype == 'created_by':
                        # code.update({header[htype]: {"type": "created_by", "created_by": {}}})
                        print("The value for '{}' ('{}' type) is automatically assigned.".format(hvalue, htype))


                    if htype == 'created_time':
                        # code.update({header[htype]: {"type": "created_time", "created_time": {}}})
                        print("The value for '{}' ('{}' type) is automatically assigned.".format(hvalue, htype))
                    


                    if htype == 'date':
                        code.update({header[htype]: {"type": "date", "date": {"start": properties[header[htype]]}}})


                    if htype == 'email':
                        code.update({header[htype]: {"type": "email", "email": properties[header[htype]]}})


                    if htype == 'file':
                        print("The Notion API does not support adding '{}' ('{}' type) property to the database row. Try with Notion UI instead!".format(header[htype], htype))



                    if htype == 'formula':
                        print("The Notion API does not support adding '{}' ('{}' type) property to the database row. Try with Notion UI instead!".format(header[htype], htype))


                    if htype == 'last_edited_by':
                        # code.update({header[htype]: {"type": "last_edited_by", "last_edited_by": {}}})
                        print("The value for '{}' ('{}' type) is automatically assigned.".format(hvalue, htype))



                    if htype == 'last_edited_time':
                        # code.update({header[htype]: {"type": "last_edited_time", "last_edited_time": {}}})     
                        print("The value for '{}' ('{}' type) is automatically assigned.".format(hvalue, htype))
               


                    if htype == 'multi_select':
                        selection = [{"name": select} for select in properties[hvalue]]
                        # code.update({header['multi_select']: {"multi_select": selection}})           
                        code.update({hvalue: {"multi_select": selection}})


                    if htype == 'number':
                        if isinstance(header[htype], list): 
                            code.update({header[htype][0]: {"type": "number", "number": properties[header[htype][0]]}})

                        else:
                            code.update({header[htype]: {"type": "number", "number": properties[header[htype]]}})


                    if htype == 'people':
                        # code.update({header[htype]: {"type": "people", "people": {}}})
                        print("The Notion API does not support adding '{}' ('{}' type) property to the database row. Try with Notion UI instead!".format(header[htype], htype))



                    if htype == 'phone_number':
                        code.update({header[htype]: {"type": "phone_number", "phone_number": properties[header[htype]]}})


                    if htype == 'relation':
                        print("The Notion API does not support adding '{}' ('{}' type) property to the database row. Try with Notion UI instead!".format(header[htype]['name'], htype))


                    if htype == 'rollup':
                        print("The Notion API does not support adding '{}' ('{}' type) property to the database row. Try with Notion UI instead!".format(header[htype]['name'], htype))


                    if htype == 'select':
                        code.update({hvalue: {"select": {"name": properties[hvalue]}}})


                    if htype == 'status':
                         # code.update({hvalue: {"status": {"name": "Not started", "color": "defualt"}}})                   
                        print("The Notion API does not support adding '{}' ('{}' type) property to the database row. Try with Notion UI instead!".format(header[htype], htype))


                    if htype == 'title':
                        if copy:
                            code.update({header[htype]: {"type": "title", "title": [{"text": {"content": properties[header[htype]]+" (copy)"}}],}})

                        else:
                            code.update({header[htype]: {"type": "title", "title": [{"text": {"content": properties[header[htype]]}}],}})


                    if htype == 'text':
                        code.update({header[htype]: {"type": "rich_text", "rich_text": [{"type": "text", "text": {"content": properties[header[htype]]}}],}})


                    if htype == 'url':
                        code.update({header[htype]: {"type": "url", "url": properties[header[htype]]}})

    return code




def get_properties_code_without_id(properties_code: dict):

    pcode = properties_code
    pcode_new = {}
    for k, v in pcode.items():
        if v['type'] in ['created_by', 'created_time', 'last_edited_by', 'last_edited_time', 'file', 'formula', 'people', 'relation', 'rollup', 'status']:
            pass

        elif v['type'] == 'select':
            types = v['type']
            v.pop('id')
            if v[types]:
                v[types].pop('id')
            pcode_new.update({k: v})

            
        elif v['type'] == 'multi_select':
            types = v['type']
            v.pop('id')
            if v[types] != []:
                v[types][0].pop('id')
            pcode_new.update({k: v})
          
        else:
            v.pop('id')
            pcode_new.update({k: v})

    return pcode_new




def get_properties_from_id(page_id: str, copy = False) -> tuple:

    prop_code = notion.pages.retrieve(page_id)['properties']
    prop = {}

    for k, v in prop_code.items():
        for k1, v1 in v.items():

            if k1 in ['created_by', 'created_time', 'last_edited_by', 'last_edited_time', 'file', 'formula', 'people', 'relation', 'rollup', 'status']:
                pass

            if k1 == 'checkbox':
                prop.update({k: v1})

            if k1 == 'date':
                prop.update({k: v1['start']})

            if k1 == 'email':
                prop.update({k: v1})

            if k1 == 'multi_select':
                prop.update({k: [v2['name'] for v2 in v1]})

            if k1 == 'number':
                prop.update({k: v1})

            if k1 == 'phone_number':
                prop.update({k: v1})

            if k1 == 'rich_text':
                prop.update({k: v1[0]['text']['content']})

            if k1 == 'select':
                prop.update({k: v1['name']})

            if k1 == 'title':
                if copy:
                    prop.update({k: v1[0]['text']['content']  + " (copy)"})
                    name = v1[0]['text']['content'] + " (copy)"

                else:
                    prop.update({k: v1[0]['text']['content']})
                    name = v1[0]['text']['content']

            if k1 == 'url':
                prop.update({k: v1})

    return name, prop





class Page():


    def __init__(self, name: str = "", url: str = ""):
        self.name = name
        self.url = url
        self.id = ""
        # self.icon = "📄"
        self.icon = ""
        self.properties = {}
        self.properties_code = {}
        self.linked = False

        if self.url != "":
            self.id = get_parent_id(self.url) 
            self.linked = True  

            source_pg_info = get_page_info(self.url)
            self.properties = source_pg_info['properties']
            self.properties_code = source_pg_info['properties_code']
            self.icon = source_pg_info['icon']
            
            # Page is NOT database page
            if source_pg_info['parent'] in  ['workspace', 'page_id']:
                try:
                    self.name = source_pg_info['properties']['title']
                except:
                    self.name = ""

            # page is database page
            else:
                self.name = source_pg_info['page_name']




    def set_icon(self, icon: str):

        # if self.id == "":
        # self.icon = icon
        if self.id == "":
            # self.icon = icon
            self.icon = {"type": "emoji", "emoji": icon}




    def get_info(self) -> dict:
        result = notion.pages.retrieve(page_id = self.id)
        return result




    ############# Page related method #####################
    #######################################################


    def add_page(self, page: object):

        # icon_code = None
        
        # if page.icon != "":
        #     icon_code = {'emoji': page.icon}

        icon = page.icon

        if page.icon == "":
            icon = None
        
        if page.url != "":
            pg_info = get_page_info(page.url)
            properties_code = pg_info['properties_code']
            icon = pg_info['icon']
            if pg_info['parent'] == 'database_id':
                print('You cannot add a database page to the page!!!')


        else:
            if page.properties != {}:
                properties_code = get_properties_code(self.properties, **page.properties)


            else:
                properties_code = {'title': {'id': 'title', 'type': 'title', 'title': [{'type': 'text', 'text': {'content': 'blank page', 'link': None},
                'annotations': {'bold': False, 'italic': False, 'strikethrough': False, 'underline': False, 'code': False, 'color': 'default'},
                'plain_text': 'blank page','href': None}]}}
                # properties_code = {'title': {'id': 'title', 'type': 'title', 'title': []}}



        new_page = notion.pages.create(parent = {"page_id": self.id}, icon = icon, properties = properties_code)
        page.url = new_page['url']
        page.id = new_page['id']

        new_pg_info = get_page_info(page.url)
        # page.id = new_pg_info['id']
        page.properties = new_pg_info['properties']
        page.properties_code = new_pg_info['properties_code']
        change_page_title(page.name, page.url)




    def add_properties(self, properties: dict):

        self.properties = properties




    def copy_page(self, page: object):

        source_pg_info = get_page_info(page.url)
        copy_page = Page("copy page")
        properties = source_pg_info['properties']
        properties_code = source_pg_info['properties_code']
        icon = source_pg_info['icon']

        new_page = notion.pages.create(parent = {"page_id": self.id}, icon = icon, properties = properties_code)

        source_name = source_pg_info['page_name'] + " (copy)"
        if source_pg_info['page_name'] == "":
            source_name = "New page (copy)"

        change_page_title(source_name, new_page['url'])
        
        copy_pg_info = get_page_info(new_page['url'])
        copy_page.properties = copy_pg_info['properties']
        copy_page.properties_code = copy_pg_info['properties_code']
        copy_page.id = new_page['id']
        copy_page.url = new_page['url']

        content_copy = get_block_info(page.url)[2]
        new_blocks = notion.blocks.children.append(block_id = copy_page.id, children = content_copy)
        

        return copy_page




    ######### Database related method #####################
    #######################################################

    def add_database(self, database: object, inline: bool = False):
        parent_page_id_code = {"type": "page_id", "page_id": self.id}
        db_title_code = [{"type": "text", "text": {"content": database.name}}]
        # db_icon_code = {"type": "emoji", "emoji": database.icon}
        
        icon = database.icon
        if database.icon == "":
            icon = None
        # db_properties_code = get_header_code(**database.properties)
        db_properties_code = get_header_code(database.properties)

        new_db = notion.databases.create(parent = parent_page_id_code, title = db_title_code, properties = db_properties_code, icon = icon, is_inline = inline)
        database.id = new_db['id']
        database.url = new_db['url']




    def copy_database(self, database: object, inline: bool = False):
        name = database.name + " (copy)"
        # new_db = Database(name)
        # new_db.link_to_url(database.url)
        new_db = Database(name, database.url)
        self.add_database(new_db, inline)
        # new_db.name = name
        change_database_title(name, new_db.url)

        current_info = get_database_info(new_db.url)
        new_db.properties = current_info['properties']
        new_db.properties_code = current_info['properties_code']
        new_db.name = current_info['title']
        new_db.icon = current_info['icon']

        return new_db




    def copy_database_with_content(self, database: object, inline: bool = False):
        name = database.name + " (copy)"
        new_db = Database(name, database.url)
        self.add_database(new_db, inline)
        change_database_title(name, new_db.url)

        
        db_pg_list = notion.databases.query(**{"database_id": database.id,})['results']

        for i in reversed(range(len(db_pg_list))):
            db_pg_info = get_page_info(db_pg_list[i]['url'])

            # icon_code = None
            # if db_pg_list[i]['icon']:
            #     icon_code = {"type": "emoji", "emoji": db_pg_list[i]['icon']['emoji']}

            # icon_code = None
            if db_pg_list[i]['icon']:
                icon = db_pg_list[i]['icon']

            else:
                icon = None


            properties_code = db_pg_info['properties_code']
            new_db_page = notion.pages.create(parent = {"database_id": new_db.id}, icon = icon, properties = properties_code)

            # copy page content
            content_copy = get_block_info(db_pg_list[i]['url'])[2]
            new_blocks = notion.blocks.children.append(block_id = new_db_page['id'], children = content_copy)


        current_info = get_database_info(new_db.url)
        new_db.properties = current_info['properties']
        new_db.properties_code = current_info['properties_code']
        new_db.name = current_info['title']
        new_db.icon = current_info['icon']

        return new_db




    ############# Block related method #####################
    #######################################################


    def add_column_list_and_column_block(self, block_list: object):
        if len(block_list) == 1:
            print('More than one block needs to be assigned!!')

        else:
            column_list = []
            for block in block_list:
                column_list.append({'type': 'column', 'column': {'children': block.code_list}})
            column_list_code = [{'type': 'column_list', 'column_list': {'children': column_list}}]

            new_block = notion.blocks.children.append(block_id = self.id, children = column_list_code)
            
            return new_block




    def add_block(self, block: object):
        
        if block.sync:
            children = [{"type": "synced_block", "synced_block": {"synced_from": None, "children": []}}]
            new_block_empty = notion.blocks.children.append(block_id = self.id, children = children)
            block_id = new_block_empty['results'][0]['id']
            new_block = notion.blocks.children.append(block_id = block_id, children = block.code_list)
            block.sync_id = block_id

        else:
            new_block = notion.blocks.children.append(block_id = self.id, children = block.code_list)


        for i, nb in enumerate(new_block['results']):
            child_name = "child"+str(i)
            block.id_list.append({child_name: nb["id"]})

            if isinstance(block.content_list[i], str):
                block.content_list[i] = {child_name: block.content_list[i]}

        block.parent_id = self.id
        block.parent_url = self.url




    def copy_sync_block(self, block: object):

        try:
   
            new_children = [{"type": "synced_block", "synced_block": {"synced_from": {"block_id": block.sync_id},},}]
            new_block = notion.blocks.children.append(block_id = self.id, children = new_children)

            block = Block()
            block.replica_id = new_block['results'][0]['id']
            block.parent_url = self.url
            block.parent_id = self.id
            block.sync = True

            new_block_info = get_block_info_from_id(block.replica_id)
            block.id_list = new_block_info[0]
            block.content_list = new_block_info[1]
            block.code_list = new_block_info[2]

            return block

        except:
            print("This is only applicable to sync block !!!!")




    def copy_content(self, page: object):

        content_copy = get_block_info(page.url)[2]
        new_blocks = notion.blocks.children.append(block_id = self.id, children = content_copy)
        
        block_copied = Block('block_copy')
        block_copied.code_list = content_copy
        # block_copied.id = new_blocks['results'][0]['id']

        for nb in new_blocks['results']:
            block_copied.id_list.append(nb["id"])


        return block_copied
 




    def update_content(self, block: object, children: list):

        children_name = []
        children_code = []
        children_content = []

        for k, v in children.items():
            children_name.append(k)
            children_code.append(v['code'])
            children_content.append(v['content'])


        for i, block_id in enumerate(block.id_list):
            
            for j, child_name in enumerate(children_name):
            
                if child_name in block_id:
                    
                    child_id = block_id[child_name]
                    child_code = children_code[j]

                    # new_child = notion.blocks.children.append(block_id = self.id, after = child_id, children = [child_code])
                    new_child = notion.blocks.children.append(block_id = self.id, before = child_id, children = [child_code])

                    notion.blocks.delete(block_id = child_id)

                    block.code_list[i] = child_code
                    block.content_list[i][child_name] = children_content[j]
                    block.id_list[i][child_name] = new_child['results'][0]['id']    



    def update_icon(self, icon: str):
        icon_code = {"type": "emoji", "emoji": icon}
        notion.pages.update(page_id = self.id, icon = icon_code, properties = {})
        self.icon = icon_code





class Database:

    def __init__(self, name: str = "", url: str = ""):
        self.name = name
        self.url = url
        self.id = ""
        self.icon = ""
        self.properties = {}
        self.properties_code = {}
        self.linked = False

        if self.url != "":
            self.id = get_parent_id(self.url)
            self.linked = True

            source_db_info = get_database_info(self.url)
            self.properties = source_db_info['properties']
            self.properties_code = source_db_info['properties_code']

            if source_db_info['icon'] != None:
                self.icon = source_db_info['icon']




    def get_info(self)-> dict:

        result = notion.databases.retrieve(database_id = self.id)

        return result




    def set_header(self, db_header: dict):

        # if self.id = "":
            self.properties = db_header




    def set_icon(self, icon: str):

        if self.id == "":
            # self.icon = icon
            self.icon = {"type": "emoji", "emoji": icon}

        else:
            print("This is linked to the existing database and you cannot modify the icon")


    def get_icon(self):
        try:
            img = self.icon["emoji"]

        except:
            img = self.icon["external"]

        return img




    ############# Page related method #####################
    #######################################################


    def add_page(self, page: object):

        # icon_code = {"emoji": page.icon}
        # if page.icon == "":
        #     icon_code = None

        icon = page.icon

        if icon == "":
            icon = None

        # Only if page is database page
        if page.url != "":
            pg_info = get_page_info(page.url)
            icon = pg_info['icon']

            if pg_info['parent'] == 'database_id':  # if it's database page
                properties_code = pg_info['properties_code']
                # new_page = notion.pages.create(parent = {"database_id": self.id}, icon = icon_code, properties = properties_code)
                new_page = notion.pages.create(parent = {"database_id": self.id}, icon = icon, properties = properties_code)


                # copy page content
                content_copy = get_block_info(page.url)[2]
                new_blocks = notion.blocks.children.append(block_id = new_page['id'], children = content_copy)
 
                page.url = new_page['url']



            else: # if not database page
                print('This is not database page. Try with database page!')

        else:
            if page.properties != {}: # database page type
                properties_code = get_properties_code(self.properties, **page.properties)
                new_page = notion.pages.create(parent = {"database_id": self.id}, icon = icon, properties = properties_code)
                page.url = new_page['url']

            else:  # no database page type
                print("This is not database page. Try with database page")

        new_pg_info = get_page_info(new_page['url'])
        page.id = new_pg_info['id']
        # page.url = new_pg_info['url']
        page.properties = new_pg_info['properties']
        page.properties_code = new_pg_info['properties_code']

        # return page

 


    def copy_page(self, page: object):

        copy = True
        source_pg_info = get_page_info(page.url)
        new_db_page = Page("new db page")

        # page is database page
        if source_pg_info['parent'] == 'database_id':

            icon = source_pg_info['icon']

            if page.icon == "":
                icon = None

            properties_code = source_pg_info['properties_code']
            properties = source_pg_info['properties']
            new_page = notion.pages.create(parent = {"database_id": self.id}, icon = icon, properties = properties_code)
            change_page_title(source_pg_info['page_name'] + " (copy)", new_page['url'])
            new_page_info = get_page_info(new_page['url'])
            new_db_page.properties = new_page_info['properties']
            new_db_page.properties_code = new_page_info['properties_code']
            new_db_page.id = new_page['id']
            new_db_page.url = new_page['url']

            # copy page content
            content_copy = get_block_info(page.id)[2]
            new_blocks = notion.blocks.children.append(block_id = new_page['id'], children = content_copy)

            return new_db_page


        # page is not database page
        else:
            print('This is not be database page! Try with database page!')




    def update_page_properties(self, page: object, new_properties: dict):
        new_properties_code = get_properties_code(self.properties, **new_properties)

        # if page.icon != "":
        #     icon_code = {'emoji': page.icon}

        if page.icon != "":
            icon = page.icon
            notion.pages.update(page_id = page.id, icon = icon, properties = new_properties_code)
        else:
            notion.pages.update(page_id = page.id, properties = new_properties_code)

        source_pg_info = get_page_info(page.url)
        page.properties = source_pg_info['properties']
        page.properties_code = source_pg_info['properties_code']



    def update_icon(self, icon: str):

        icon_code = {"type": "emoji", "emoji": icon}
        notion.databases.update(database_id = self.id, icon = icon_code)
        self.icon = icon_code



    def update_page_icon(self, page: object, icon: str):

        icon_code = {"type": "emoji", "emoji": icon}
        notion.pages.update(page_id = page.id, icon = icon_code, properties = {})





def bookmark(caption: str,  url: str) -> object:
    code = {"type": "bookmark", "bookmark": {"caption": [{"type": "text", "text": {"content": caption, "link": None}}], "url": url}}
    return {"code": code, "content": "bookmark"}


def breadcrumb() -> object:
    c = {"type": "breadcrumb", "breadcrumb": {}}
    return {"code": c, "content": "breadcrumb"}


def bulleted_list_item(main: str, subs: list = []) -> object:
    child = []
    for sub in subs:
        child.append({"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": sub}}],"color": "default",},})
    code = {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": main}}], 
    "color": "default", "children": child,},}
    return {"code": code, "content": "bulleted_list_item"}


def callout(content: str, bold: bool = False, italic: bool = False, strikethrough: bool = False, 
    underline: bool = False, code: bool = False, color: str = "default",) -> object:
    code = {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": content}, "annotations": {"bold": bold, "italic": italic,
     "strikethrough": strikethrough, "underline": underline, "code": code,"color": color,},},],},}
    return {"code": code, "content": "callout"}


def column_list_and_column(block_list: object):
    if len(block_list) == 1:
        print('More than one block needs to be assigned!!')

    else:
        column_list = []

        for block in block_list:
            column_list.append({'type': 'column', 'column': {'children': block.code_list}})

        # column_list_code = [{'type': 'column_list', 'column_list': {'children': column_list}}]
        column_list_code = {'type': 'column_list', 'column_list': {'children': column_list}}


        return {"code": column_list_code, "content": "column_list_and_column"}


def code(content: str, language: str) -> object:
    c = {"type": "code", "code": {"caption": [], "rich_text": [{"type": "text", "text": {"content": content}}], "language": language,},}
    return {"code": c, "content": "code"}


def divider() -> object:
    c = {"type": "divider", "divider": {}}
    return {"code": c, "content": "divider"}


def embed(url: str) -> object:
    code = {"type": "embed", "embed": {"url": url}}
    return {"code": code, "content": "embed"}


def equation(content: str) -> object:
    c = {"type": "equation", "equation": {"expression": content,},}
    return {"code": c, "content": "equation"}


def file(name: str, caption: str, url: str) -> object:
    code = {"type": "file", "file": {"caption": [{"type": "text", "text": {"content": caption, "link": None}}],
     "type": "external", "external": {"url": url},"name": name}}
    return {"code": code, "content": "file"}


def heading(content: str, header_type: int = 2, color: str= 'default', child: dict = {}, toggle: bool = False) -> object:
    if header_type == 1:
        heading_size = "heading_1"
    elif header_type == 2:
        heading_size = "heading_2"
    elif header_type == 3:
        heading_size = "heading_3"
    else: 
        print(" Enter number 1 ~ 3. 1 -> heaindg1, 2-> heading2, 3-> heading3 ")

    code = {heading_size: {"rich_text": [{"type": "text", "text": {"content": content},}], "color": color},}

    if toggle:
        child = {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text","text": {"content": "Toggle content"},}]},}
        code = {"type": heading_size, heading_size: {"rich_text": [{"type": "text", "text": {"content": content},}], "children": [child]},}

    return {"code": code, "content": heading_size}


def image(url: str) -> object:
    code = {"type": "image", "image": {"type": "external", "external": {"url": url}}}
    return {"code": code, "content": "image"}


def mention(d_type: str, id: str) -> object:
    """
    support d_type : database, page 
    """
    c = {"type": "paragraph", "paragraph": {"rich_text": [{"type": "mention", "mention": {"type": d_type, d_type: {"id": id}},}],},}
    return {"code": c, "content": "mention"}


def numbered_list_item(main: str, subs: list = []) -> object:
    child = []
    for sub in subs:
        child.append({"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": sub}}],"color": "default",},})
    c = {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": main, "link": None},}], 
    "color": "default", "children": child,},}
    return {"code": c, "content": "numbered_list_item"}


def paragraph(content: str, bold: bool = False, italic: bool = False, strikethrough: bool = False, 
    underline: bool = False, code: bool = False, color: str = "default",) -> object:    
    code = {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": content,},"annotations": {"bold": bold,"italic": italic, 
    "strikethrough": strikethrough, "underline": underline, "code": code, "color": color,},}],},}
    return {"code": code, "content": "text"}


def pdf(url: str) -> object:
    code = {"type": "pdf", "pdf": {"type": "external", "external": {"url": url}}}
    return {"code": code, "content": "pdf"}


def quote(content: str, color: str = "blue_background") -> object:
    c = {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": content, "link": None},}], "color": color,},}
    return {"code": code, "content": "quote"}


def space() -> object:
    # code = {"heading_3": {"rich_text": [{"type": "text", "text": {"content": " "},}],},}
    code = {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": " ",},"annotations": {"bold": False,"italic": False, 
    "strikethrough": False, "underline": False, "code": False, "color": "default",},}],},}
    return {"code": code, "content": "space"}


def table(header: list, content: list, has_row_header: bool = False) -> object:
    header_code = [[{"type": "text", "text": {"content": h}}] for h in header]
    content_code = []
    for row in content:
        content_code.append([[{"type": "text", "text": {"content": r}}] for r in row])
    child = [{"type": "table_row", "table_row": {"cells": header_code},}]
    for row_code in content_code:
        child.append({"type": "table_row", "table_row": {"cells": row_code},})
    code = {"type": "table", "table": {"table_width": len(header), "has_column_header": True, "has_row_header": has_row_header,
    "children": child,},}
    return {"code": code, "content": "table"}


def table_of_contents() -> object:
    code = {"type": "table_of_contents", "table_of_contents": {"color": "default"}}
    return {"code": code, "content": "table_of_contents"}


def to_do(main: str, subs: list = [], checked: bool = False, color: str = "default"):
    # child = [{"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": subs}}]}}] paragraph
    child = [{"to_do": {"rich_text": [{"type": "text", "text": {"content": sub }}], "checked": checked, "color": color}} for sub in subs]
    code = {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": main }}], "checked": checked, "color": color, "children": child}}
    return {"code": code, "content": "to_do"}


def toggle_blocks(main: str, subs: list = [], color: str = "default", sub_toggle = False) -> object:
    child = []

    paragraph = "paragraph"

    if sub_toggle: # sub-menu is a toggle_block
        paragraph = "toggle"

    for sub in subs:
        child.append({"object": "block", "type": paragraph, paragraph: {"rich_text": [{"type": "text", "text": {"content": sub},}]},})
    code = {"type": "toggle", "toggle": {"rich_text": [{"type": "text", "text": {"content": main},}], "color": color, "children": child,},}
    return {"code": code, "content": "toggle"}


def video(url: str) -> object:
    code = {"type": "video", "video": {"type": "external", "external": {"url": url}}}
    return {"code": code, "content": "video"}






class Block:


    def __init__(self, name: str = "", parent_url: str = "", sync: bool = False):
        self.name = name
        self.parent_id = ""
        self.parent_url = parent_url
        self.sync_id = ""
        self.replica_id = ""
        self.id_list = []
        self.content_list = []
        self.code_list = []
        self.linked = False
        self.sync = sync


        if self.parent_url != "":
            self.parent_id = get_parent_id(self.parent_url)
            self.linked = True

            source_block_info = get_block_info(self.parent_url)
            self.id_list = source_block_info[0]
            self.content_list = source_block_info[1]
            self.code_list = source_block_info[2]




    def bookmark(self, caption: str,  url: str) -> object:
        code = {"type": "bookmark", "bookmark": {"caption": [{"type": "text", "text": {"content": caption, "link": None}}], "url": url}}
        self.code_list.append(code)
        self.content_list.append("bookmark")
        return self




    def breadcrumb(self) -> object:
        c = {"type": "breadcrumb", "breadcrumb": {}}
        self.code_list.append(c)
        self.content_list.append("breadcrumb")
        return self




    def bulleted_list_item(self, main: str, subs: list = []) -> object:

        child = []

        for sub in subs:
            child.append({"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": sub}}],"color": "default",},})

        code = {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": main}}],
        "color": "default", "children": child,},}


        self.code_list.append(code)
        self.content_list.append("bulleted_list_item")

        return self




    def callout(self, content: str, bold: bool = False, italic: bool = False, strikethrough: bool = False, 
        underline: bool = False, code: bool = False, color: str = "default",) -> object:
        
        code = {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": content}, "annotations": {"bold": bold, "italic": italic,
         "strikethrough": strikethrough, "underline": underline, "code": code,"color": color,},},],},}

        self.code_list.append(code)
        self.content_list.append("callout")

        return self




    def child_database():
        pass




    def child_page():
        pass



    def column_list_and_column(self, block_list: object):
        if len(block_list) == 1:
            print('More than one block needs to be assigned!!')

        else:
            column_list = []
 
            for block in block_list:
                column_list.append({'type': 'column', 'column': {'children': block.code_list}})
 
            column_list_code = [{'type': 'column_list', 'column_list': {'children': column_list}}]

            # new_block = notion.blocks.children.append(block_id = self.id, children = column_list_code)
            self.code_list.append(column_list_code[0])
            self.content_list.append("column_list_and_column")
            
            return self





    def code(self, content: str, language: str) -> object:
        c = {"type": "code", "code": {"caption": [], "rich_text": [{"type": "text", "text": {"content": content}}], "language": language,},}
        self.code_list.append(c)
        self.content_list.append("code")

        return self




    def divider(self) -> object:
        c = {"type": "divider", "divider": {}}
        self.code_list.append(c)
        self.content_list.append("divider")

        return self




    def embed(self, url: str) -> object:
        code = {"type": "embed", "embed": {"url": url}}

        self.code_list.append(code)
        self.content_list.append("embed")

        return self




    def equation(self, content: str) -> object:
        c = {"type": "equation", "equation": {"expression": content,},}
        self.code_list.append(c)
        self.content_list.append("equation")

        return self




    def file(self, name: str, caption: str, url: str) -> object:

        code = {"type": "file", "file": {"caption": [{"type": "text", "text": {"content": caption, "link": None}}],
         "type": "external", "external": {"url": url},"name": name}}

        self.code_list.append(code)
        self.content_list.append("file")

        return self




    def heading(self, content: str, header_type: int = 2, color: str= 'default', child: dict = {}, toggle: bool = False) -> object:

        if header_type == 1:
            heading_size = "heading_1"
        
        elif header_type == 2:
            heading_size = "heading_2"
        
        elif header_type == 3:
            heading_size = "heading_3"

        else: 
            print(" Enter number 1 ~ 3. 1 -> heaindg1, 2-> heading2, 3-> heading3 ")

        code = {heading_size: {"rich_text": [{"type": "text", "text": {"content": content},}], "color": color},}

        if toggle:
            child = {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text","text": {"content": "Toggle content"},}]},}
            code = {"type": heading_size, heading_size: {"rich_text": [{"type": "text", "text": {"content": content},}], "children": [child]},}

        self.code_list.append(code)
        self.content_list.append(heading_size)

        return self




    def image(self, url: str) -> object:

        code = {"type": "image", "image": {"type": "external", "external": {"url": url}}}

        self.code_list.append(code)
        self.content_list.append("image")

        return self




    def link_preview():
        
        pass




    def mention(self, d_type: str, id: str) -> object:
        """
        support d_type : database, page 
        """
        c = {"type": "paragraph", "paragraph": {"rich_text": [{"type": "mention", "mention": {"type": d_type, d_type: {"id": id}},}],},}
        self.code_list.append(c)
        self.content_list.append("mention")

        return self




    def numbered_list_item(self, main: str, subs: list = []) -> object:

        child = []

        for sub in subs:
            child.append({"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": sub}}],"color": "default",},})

        c = {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": main, "link": None},}], 
        "color": "default", "children": child,},}
        self.code_list.append(c)
        self.content_list.append("numbered_list_item")

        return self




    def paragraph(self, content: str, bold: bool = False, italic: bool = False, strikethrough: bool = False, 
        underline: bool = False, code: bool = False, color: str = "default",) -> object:
        
        code = {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": content,},"annotations": {"bold": bold,"italic": italic, 
        "strikethrough": strikethrough, "underline": underline, "code": code, "color": color,},}],},}

        self.code_list.append(code)
        self.content_list.append("text")

        return self




    def pdf(self, url: str) -> object:

        code = {"type": "pdf", "pdf": {"type": "external", "external": {"url": url}}}

        self.code_list.append(code)
        self.content_list.append("pdf")

        return self




    def quote(self, content: str, color: str = "blue_background") -> object:
        c = {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": content, "link": None},}], "color": color,},}

        self.code_list.append(c)
        self.content_list.append("quote")

        return self




    def space(self) -> object:

        code = {"heading_3": {"rich_text": [{"type": "text", "text": {"content": " "},}],},}

        code = {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": " ",},"annotations": {"bold": False,"italic": False, 
        "strikethrough": False, "underline": False, "code": False, "color": "default",},}],},}

        self.code_list.append(code)
        self.content_list.append("space")

        return self




    def table(self, header: list, content: list, has_row_header: bool = False) -> object:

        header_code = [[{"type": "text", "text": {"content": h}}] for h in header]
        content_code = []

        for row in content:
            content_code.append([[{"type": "text", "text": {"content": r}}] for r in row])

        child = [{"type": "table_row", "table_row": {"cells": header_code},}]

        for row_code in content_code:
            child.append({"type": "table_row", "table_row": {"cells": row_code},})


        code = {"type": "table", "table": {"table_width": len(header), "has_column_header": True, "has_row_header": has_row_header,
        "children": child,},}

        self.code_list.append(code)
        self.content_list.append("table")

        return self




    def table_of_contents(self) -> object:
        code = {"type": "table_of_contents", "table_of_contents": {"color": "default"}}

        self.code_list.append(code)
        self.content_list.append("table_of_contents")

        return self




    def template():
        pass




    def to_do(self, main: str, subs: list = [], checked: bool = False, color: str = "default"):
        # child = [{"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": subs}}]}}] paragraph
        child = [{"to_do": {"rich_text": [{"type": "text", "text": {"content": sub }}], "checked": checked, "color": color}} for sub in subs]
        code = {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": main }}], "checked": checked, "color": color, "children": child}}

        self.code_list.append(code)
        self.content_list.append("to_do")

        return self




    def toggle_blocks(self, main: str, subs: list = [], color: str = "default", sub_toggle=False) -> object:

        child = []

        paragraph = "paragraph"

        if sub_toggle: # sub-menu is a toggle_block
            paragraph = "toggle"

        for sub in subs:
            child.append({"object": "block", "type": paragraph, paragraph: {"rich_text": [{"type": "text", "text": {"content": sub},}]},})

        code = {"type": "toggle", "toggle": {"rich_text": [{"type": "text", "text": {"content": main},}], "color": color, "children": child,},}

        self.code_list.append(code)
        self.content_list.append("toggle")

        return self



    def video(self, url: str) -> object:
        code = {"type": "video", "video": {"type": "external", "external": {"url": url}}}

        self.code_list.append(code)
        self.content_list.append("video")

        return self



























