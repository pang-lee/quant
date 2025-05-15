import json, os, copy

json_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'setting.json')

def open_json_file():
    # 读取 JSON 文件
    with open(json_file_path, 'r') as f:
        settings = json.load(f)

    # 解析 $ref 引用并应用共享参数
    params = settings['params']
    for _, items in settings['items'].items():
        for item in items:
            # 如果 `params` 使用了 `$ref`，则将其替换为全局共享参数, 否则保留单独定义的参数
            if item['params'].get('$ref') == '#/params':
                item['params'] = params

    return settings

def update_settings(target_key, target_codes, strategy, new_params):
    try:
        # 读取 JSON 文件
        with open(json_file_path, 'r') as f:
            settings = json.load(f)

        # 仅遍历指定的 item_key（例如 future, stock）
        item_list = settings["items"].get(target_key, [])
        for item in item_list:
            # 完整比较两个列表是否相同
            if item.get("strategy") == strategy:
                if sorted(item.get("code", [])) == sorted(target_codes):

                    # 检查是否存在 "$ref" 引用
                    if "$ref" in item.get("params", {}):
                        updated_params = copy.deepcopy(settings["params"])
                        updated_params.update(new_params)
                        item["params"] = updated_params
                    else:
                        item["params"].update(new_params)

                    break

        with open(json_file_path, "w") as file:
            json.dump(settings, file, indent=4)

    except Exception as e:
        raise RuntimeError(f"update_settings Error: {e}")

    return