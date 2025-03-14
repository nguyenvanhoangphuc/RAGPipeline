import re
import json
# from docx import Document

def convert_japanese_numbers(text):
    jp_numbers = "０１２３４５６７８９"
    latin_numbers = "0123456789"
    translation_table = str.maketrans(jp_numbers, latin_numbers)
    return text.translate(translation_table)

# def extract_text_with_numbering(docx_path):
#     """
#     Trích xuất nội dung từ file .docx, nối các đoạn văn bằng ký tự '@'
#     """
#     doc = Document(docx_path)
#     extracted_text = []
#     for para in doc.paragraphs:
#         text = para.text.strip()
#         if text:
#             extracted_text.append(text)
#     return '@'.join(extracted_text)

def parse_text_to_json(text):
    data = {"chapters": []}
    chapter_dict = {}
    article_dict = {}
    clause_dict = {}

    current_chapter = None
    current_article = None
    current_clause = None
    
    lines = text.split("\n")
    for line in lines:
        # Loại bỏ nhãn (ví dụ: #chuong, #dieu, …)
        clean_line = re.sub(r'#\w+', '', line).strip()
        if not clean_line:
            continue
        
        # Nhận diện chương: "第<number>章 <chapter title>"
        match = re.search(r'第(\d+)章\s+(.+)', clean_line)
        if match:
            chapter_num = match.group(1)
            chapter_title = match.group(2)
            current_chapter = {
                "chapter_number": chapter_num,
                "chapter_title": chapter_title,
                "articles": [],
                "raw_content": clean_line  # Header của chương
            }
            data["chapters"].append(current_chapter)
            # Tạm thời gán raw_content (sẽ cập nhật sau)
            chapter_dict[chapter_num] = current_chapter["raw_content"]
            current_article = None
            current_clause = None
            continue
        
        # Nhận diện điều: "第<number>条 <article title>"
        match = re.search(r'第(\d+)条\s+(.+)', clean_line)
        if match:
            article_num = match.group(1)
            article_title = match.group(2)
            current_article = {
                "article_number": article_num,
                "article_title": article_title,
                "clauses": [],
                "raw_content": clean_line  # Header của điều
            }
            if current_chapter:
                current_chapter["articles"].append(current_article)
            else:
                if not data["chapters"]:
                    empty_chapter = {
                        "chapter_number": "",
                        "chapter_title": "",
                        "articles": [],
                        "raw_content": ""
                    }
                    data["chapters"].append(empty_chapter)
                    current_chapter = empty_chapter
                current_chapter["articles"].append(current_article)
            # Tạm thời gán raw_content (sẽ cập nhật sau)
            article_dict[article_num] = current_article["raw_content"]
            current_clause = None
            continue
        
        # Nhận diện khoản: bắt đầu bằng số và khoảng trắng (ví dụ: "1  Nội dung...")
        match = re.search(r'^(\d+)\s+(.+)', clean_line)
        if match:
            clause_num = match.group(1)
            clause_title = match.group(2)
            current_clause = {
                "clause_number": clause_num,
                "clause_title": clause_title,
                "sub_clauses": [],
                "raw_content": clean_line  # Header của khoản
            }
            if current_article:
                current_article["clauses"].append(current_clause)
            else:
                if not current_chapter["articles"]:
                    empty_article = {
                        "article_number": "",
                        "article_title": "",
                        "clauses": [],
                        "raw_content": ""
                    }
                    current_chapter["articles"].append(empty_article)
                    current_article = empty_article
                current_article["clauses"].append(current_clause)
            # Tạm thời gán raw_content (sẽ cập nhật sau)
            key = (current_article["article_number"], clause_num)
            clause_dict[key] = current_clause["raw_content"]
            continue
        
        # Nhận diện sub-clause dạng ký hiệu số tròn (⓪,①,②,...⑩)
        match = re.search(r'^[⓪①②③④⑤⑥⑦⑧⑨⑩]+\s+(.+)', clean_line)
        if match:
            sub_num = str(len(current_clause["sub_clauses"]) + 1) if current_clause else "1"
            sub_clause = {
                "sub_clause_number": sub_num,
                "sub_clause_content": match.group(1),
                "raw_content": clean_line
            }
            if current_clause:
                current_clause["sub_clauses"].append(sub_clause)
            else:
                empty_clause = {
                    "clause_number": "",
                    "clause_title": "",
                    "sub_clauses": [sub_clause],
                    "raw_content": ""
                }
                if current_article:
                    current_article["clauses"].append(empty_clause)
                    current_clause = empty_clause
                else:
                    if not current_chapter["articles"]:
                        empty_article = {
                            "article_number": "",
                            "article_title": "",
                            "clauses": [],
                            "raw_content": ""
                        }
                        current_chapter["articles"].append(empty_article)
                        current_article = empty_article
                    current_article["clauses"].append(empty_clause)
                    current_clause = empty_clause
            continue
        
        # Nhận diện sub-clause dạng (number) hoặc （number）
        match = re.search(r'[（\(](\d+)[）\)]\s+(.+)', clean_line)
        if match:
            sub_num = match.group(1)
            sub_clause = {
                "sub_clause_number": sub_num,
                "sub_clause_content": match.group(2),
                "raw_content": clean_line
            }
            if current_clause:
                current_clause["sub_clauses"].append(sub_clause)
            continue
        
        # Nếu dòng không khớp với bất kỳ header nào, coi đó là phần nối (continuation)
        # Dùng "\n" làm dấu xuống dòng khi nối
        if current_clause is not None:
            current_clause["raw_content"] += "\n" + clean_line
            key = (current_article["article_number"], current_clause["clause_number"])
            clause_dict[key] = current_clause["raw_content"]
            if current_article is not None:
                current_article["raw_content"] += "\n" + clean_line
                article_dict[current_article["article_number"]] = current_article["raw_content"]
        elif current_article is not None:
            current_article["raw_content"] += "\n" + clean_line
            article_dict[current_article["article_number"]] = current_article["raw_content"]
        elif current_chapter is not None:
            current_chapter["raw_content"] += "\n" + clean_line
            chapter_dict[current_chapter["chapter_number"]] = current_chapter["raw_content"]

    # Sau khi xử lý các dòng, tổng hợp nội dung và cập nhật lại dict cho chapter, article và clause
    for chapter in data["chapters"]:
        this_chapter_title = chapter["raw_content"] + "\n"
        combined_chapter = ""
        for article in chapter["articles"]:
            this_article_title = article["raw_content"] + "\n"
            combined_article = ""
            for clause in article["clauses"]:
                # Nối nội dung của clause với các sub_clause của nó
                combined_clause = clause["raw_content"]
                for sub in clause["sub_clauses"]:
                    combined_clause += "\n" + sub["raw_content"]
                clause["raw_content"] = combined_clause.strip()
                key = (article["article_number"], clause["clause_number"])
                clause_dict[key] = {
                    'chapter': this_chapter_title,
                    'article': this_article_title,
                    'clause': clause["clause_number"] + ". ",
                    'sub_clause': '-1',
                    'text': clause["raw_content"].replace(clause["clause_number"], "").strip(),
                }
                combined_article += "\n" + clause["raw_content"]
            article["raw_content"] = combined_article.strip()
            article_dict[article["article_number"]] = {
                'chapter': this_chapter_title,
                'article': this_article_title,
                'clause': '-1',
                'sub_clause': '-1',
                'text': article["raw_content"]
            }
            combined_chapter += "\n" + article["raw_content"]
        chapter["raw_content"] = combined_chapter.strip()
        chapter_dict[chapter["chapter_number"]] = {
            'chapter': this_chapter_title,
            'article': '-1',
            'clause': '-1',
            'sub_clause': '-1',
            'text': chapter["raw_content"]
        }

    root_text = {
        "Chapter": chapter_dict,
        "Article": article_dict,
        "clause": clause_dict
    }
    
    json_output = json.dumps(data, indent=2, ensure_ascii=False)
    return json_output, root_text 

def label_and_parse_text_from_content(file_content):
    patterns = [
        (r'^契約社員|^就業規則', '#name'),
        (r'^第\d+章', '#chuong'),
        (r'^第\d+条', '#dieu'),
        (r'^\d+\s', '#NL1'),
        (r'^\d+　', '#NL2'),
        (r'^[⓪①-⑨]+　', '#NL2'),
        (r'^（\d+）\s', '#NL3'),
        (r'^--　附則|^--　付則', '#chuong'),
        (r'^休職・復職規程|^賃金規程|^嘱託社員|^パートタイム・|^アルバイト|^育児介護休業規程|^職場におけるハラスメント防止に関する規程|^テレワーク勤務規程|^退職金規程', '#name'),
        (r'^施行期日', '#dieu')
    ]
    
    labeled_lines = []
    for line in file_content.splitlines():
        line = line.strip()
        if line == "":
            continue
        labeled = False
        for pattern, label in patterns:
            if re.match(pattern, line):
                labeled_lines.append(f"{line}{label}")
                labeled = True
                break
        if not labeled and not line.startswith("#"):
            if labeled_lines:
                labeled_lines[-1] += f"@{line}"
            else:
                labeled_lines.append(line)
        elif line.startswith("#"):
            labeled_lines.append(line)
    
    text = "\n".join(labeled_lines)
    text = convert_japanese_numbers(text)
    return parse_text_to_json(text)

if __name__ == "__main__":
    # --- Sử dụng --- 
    # Thay vì truyền đường dẫn, ta đọc nội dung file trước rồi truyền vào hàm.
    input_file = 'text_file1.txt'
    with open(input_file, 'r', encoding='utf-8') as infile:
        file_content = infile.read()

    json_output, root_text = label_and_parse_text_from_content(file_content)

    print("JSON Output:")
    print(json_output)
    print("\nRoot Text:")
    print(json.dumps(root_text, indent=2, ensure_ascii=False))