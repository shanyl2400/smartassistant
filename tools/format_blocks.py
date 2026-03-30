async def main(data):
    # Load the JSON data
    # with open("/root/kg_bot/retrievers_block_content1.json", "r", encoding="utf-8") as file:
    #     data = json.load(file)
    # Extract doc_name and content into a dictionary
    result = {}
    for item in data["text"]:
        retrieve_source_type = item.get("retrieve_source_type", "")
        if retrieve_source_type == "DOC_LIB":
            doc_name = item["meta"]["doc_name"]
        elif retrieve_source_type == "FAQ":
            doc_name =  item["meta"]["title"][0] if len(item["meta"]["title"]) > 0 else "未知文件名"
        elif retrieve_source_type == "USER_INPUT":
            doc_name = item["meta"]["doc_name"]
        content = item["content"]
        if doc_name in result.keys():
            result[doc_name].append(content.replace(" ",""))
        else:
            result[doc_name] = [] 
            result[doc_name].append(content.replace(" ",""))

    # Print the result
    # for doc_name, content in result.items():
    #     print(f"{doc_name}: {content[:100]}...")  # Display first 100 characters of content

    # If you want to see the full dictionary:
    # print(result)
    yield result