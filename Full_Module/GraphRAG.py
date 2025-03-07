from copy import deepcopy
from my_utils import retry_failed_batches
from typing_extensions import TypedDict
from langchain_core.documents import Document
from langgraph.graph import END, StateGraph
from typing import List, Dict, Union, Tuple

class Proposition(TypedDict):
    proposition_content: str # sửa khi trích metadata
    documents: List[Document]  # Sử dụng Document thay vì List[str]
    filtered_documents: List[Document]


class reference(TypedDict):
    text: str
    index_list: List[int]
    
class Question(TypedDict):
    question_content: Document
    rewrite_question_content: List[str]
    propositions: List[Proposition]
    ref_propositions: List[Proposition]
    direct_reference:List[Document]
    direct_reference_text:List[reference]
    direct_reference_index: List[int]
    sematic_reference:List[Document]
    generation: str

class propositions_to_rewrite(TypedDict):
    question_index: int
    proposition_index: int
    ref_propositions_index: int
    original_proposition: Proposition
    
class RootText(TypedDict):
    Chapter: Dict[int, str]
    Article: Dict[int, str]
    clause: Dict[Tuple[int, int], str]

class GraphState(TypedDict):
    questions: List[Question]  # Lưu danh sách các câu hỏi thay vì chỉ một câu hỏi
    processed_question_index: List[int]
    current_question_index: List[int]
    propositions_to_rewrite : List[propositions_to_rewrite]
    rewrite_count :int
    root_text: RootText


class GraphRAG:
    def __init__(self, extract_reference_generator, sematic_reference_generator, rewrite_clause_generator, proposition_generator, retriever, retrieval_grader, rag_chain_both, rag_chain_doc, query_transformation_generator):
        self.extract_reference_generator = extract_reference_generator
        self.sematic_reference_generator = sematic_reference_generator
        self.rewrite_clause_generator = rewrite_clause_generator
        self.proposition_generator = proposition_generator
        self.retriever = retriever
        self.retrieval_grader = retrieval_grader
        self.rag_chain_both = rag_chain_both
        self.rag_chain_doc = rag_chain_doc
        self.query_transformation_generator = query_transformation_generator

        ## create app
        workflow = StateGraph(GraphState)

        # Define the nodes
        workflow.add_node("direct_reference", self.direct_reference)
        workflow.add_node("grade_direct_reference", self.grade_direct_reference)
        workflow.add_node("rewrite_question_content", self.rewrite_question_content)
        workflow.add_node("loopback_node",self.loopback_node) 
        workflow.add_node("create_propositions", self.create_propositions) 
        workflow.add_node("retrieve", self.retrieve) 
        workflow.add_node("grade_documents", self.grade_documents)
        workflow.add_node("generation", self.generate)
        workflow.add_node("query_transformation", self.query_transformation)
        workflow.add_node("check_empty_propositions", self.check_empty_propositions)


        workflow.set_entry_point("direct_reference")
        workflow.add_edge("direct_reference", "grade_direct_reference")
        workflow.add_edge("grade_direct_reference", "rewrite_question_content")
        workflow.add_edge("rewrite_question_content", "loopback_node")
        # workflow.add_edge("direct_reference", "grade_direct_reference")
        # workflow.add_edge("sematic_reference", "grade_direct_reference")
        workflow.add_conditional_edges( "loopback_node",
                                    self.should_create_proposition,
                                    {
                                        "STILL HAVE INDEPENDENT CHUNK":"create_propositions",
                                        "NO INDEPENDENT CHUNK":END
                                    })  
        workflow.add_edge("create_propositions", "retrieve")  
        workflow.add_edge("retrieve", "grade_documents")
        workflow.add_edge("grade_documents","check_empty_propositions")
        def decide_to_generate(state):
            if len(state["propositions_to_rewrite"])!=0: 
                if state["rewrite_count"]<1:
                    return "query_transformation"
                else: return "generation" 
            else: return "generation"
        workflow.add_conditional_edges(
            "check_empty_propositions",
            decide_to_generate,
            {
                "query_transformation":"query_transformation",
                "generation":"generation"
            }
        )

        workflow.add_edge("query_transformation","grade_documents")

        workflow.add_edge("generation", "loopback_node")

        self.app = workflow.compile()

    def get_app(self):
        return self.app

    def direct_reference(self, state):
        level_order = ["Chapter", "Article", "clause", "sub_clause"]
        level_dict={"Chapter":"chapter_number","Article":"article_number","clause":"clause_number","sub_clause":"sub_clause_number"}

        def get_min_level(metadata):
            """Xác định mức chỉ số nhỏ nhất khác None trong metadata."""
            # Duyệt ngược từ mức cao nhất xuống mức thấp nhất
            # print("get_min_level")
            for level in reversed(level_order):
                if str(metadata[level]) !='-1':
                    # print(f"level: {level}")
                    return level
            return "Chapter"
        def find_sub_refer(refer):
            min_level = get_min_level(refer)
            next_min_level=level_order[level_order.index(min_level)+1]
            sub_refer = set()
            for doc in state["questions"]:
                # kiểm tra lọc doc từ chapter đến min_level
                check=True
                if str(refer['Article'])!='-1':
                    for level in level_order[1:level_order.index(min_level)+1]:
                        if level_dict[level] in doc["question_content"].metadata and doc["question_content"].metadata[level_dict[level]] != str(refer[level]):
                            check=False
                            break
                else:
                    for level in level_order[:level_order.index(min_level)+1]:
                        if level_dict[level] in doc["question_content"].metadata and doc["question_content"].metadata[level_dict[level]] != str(refer[level]):
                            check=False
                            break
                if check:
                    # append vào sub_refer từ chapter đến next_min_level
                    dict_refer = {}
                    for level in level_order[:level_order.index(next_min_level)+1]:
                        dict_refer[level]=doc["question_content"].metadata[level_dict[level]]
                    # các phần tử sau gán = -1
                    for level in level_order[level_order.index(next_min_level)+1:]:
                        dict_refer[level]=-1
                    sub_refer.add(tuple(dict_refer.items()))
                else:
                    pass
            # chuyển sub_refer từ set sang list
            sub_refer = list(sub_refer)
            # chuyển từng phần tử trong list thành dict
            for i in range(len(sub_refer)):
                sub_refer[i]=dict(sub_refer[i])
            # print(f"sub_refer {sub_refer}")
            return sub_refer
        def refer2refer_text(refer):
            min_level=get_min_level(refer)
            refer_text=""
            if min_level=="Chapter" or min_level=="Article":
                refer_text=state["root_text"][min_level][str(refer[min_level])]
            elif min_level=="clause":
                if str(refer["Article"])=='-1':
                    print("---CAN'T FIND CLAUSE---")
                else :
                    refer_text=state["root_text"][min_level][(str(refer["Article"]),str(refer[min_level]))]
            else:
                for ref_q_index,ref_q in enumerate(state["questions"]):
                    if str(refer["Article"])=='-1' or str(refer["clause"])=='-1' :
                        print("---CAN'T FIND SUB_CLAUSE---")
                        break
                    else:    
                        if (ref_q["question_content"].metadata["article_number"] == str(refer["Article"])) and \
                        (ref_q["question_content"].metadata["clause_number"] == str(refer["clause"])) and \
                        (ref_q["question_content"].metadata["sub_clause_number"] == str(refer["sub_clause"])) :
                            refer_text=f"""第{ref_q["question_content"].metadata["chapter_number"]}章　{ref_q["question_content"].metadata["chapter_title"]} \n 第{ref_q["question_content"].metadata["article_number"]}条（{ref_q["question_content"].metadata["article_title"]}）\n{ref_q["question_content"].metadata["clause_number"]}．{ref_q["question_content"].page_content}"""
            return refer_text

        def get_list_index_from_refer(refer):
            # print(refer)
            direct_reference_index=[]
            for ref_q_index,ref_q in enumerate(state["questions"]):
                if str(refer["Article"])!='-1':
                    if (str(refer["Article"])=='-1' or ref_q["question_content"].metadata["article_number"] == str(refer["Article"])) and \
                    (str(refer["clause"])=='-1' or ref_q["question_content"].metadata["clause_number"] == str(refer["clause"])) and \
                    (str(refer["sub_clause"])=='-1' or ref_q["question_content"].metadata["sub_clause_number"] == str(refer["sub_clause"])) :
                        direct_reference_index.append(ref_q_index)
                else:
                    if (str(refer["Chapter"])=='-1' or ref_q["question_content"].metadata["chapter_number"] == str(refer["Chapter"])) and \
                    (str(refer["Article"])=='-1' or ref_q["question_content"].metadata["article_number"] == str(refer["Article"])) and \
                    (str(refer["clause"])=='-1' or ref_q["question_content"].metadata["clause_number"] == str(refer["clause"])) and \
                    (str(refer["sub_clause"])=='-1' or ref_q["question_content"].metadata["sub_clause_number"] == str(refer["sub_clause"])) :
                        direct_reference_index.append(ref_q_index)
            return direct_reference_index
        
        def get_reftext(refer):
            max_length = 512
            refer_text = refer2refer_text(refer)
            index_list=get_list_index_from_refer(refer)
            if len(refer_text) < max_length:
                return [{"text":refer_text,"index_list":index_list}]  # Trả về dưới dạng danh sách
            
            sub_refers = find_sub_refer(refer)
            # print(f"sub_refers {sub_refers}")
            if not sub_refers:
                return [{"text":refer_text,"index_list":index_list}]  # Trả về dưới dạng danh sách
            
            ref_texts = []
            for sub_refer in sub_refers:
                indexes= get_list_index_from_refer(sub_refer)
                ref_texts.extend(get_reftext(sub_refer))
            return ref_texts

        print("---DIRECT REFERENCE---")
        """
        Lặp qua các proposition để trích xuất phần reference, sau đó lọc các proposition 
        thật sự liên quan bằng LLM, rồi cập nhật lại state với thông tin tham chiếu.
        đã bỏ qua sự cần thiết của chương bởi chương có thể bị sai, nên nếu có điều thì không cần xét chương
        """
        #Kiểm tra độ dài tham chiếu nếu lớn hơn max_length thì kiểm tra cấp độ nhỏ hơn, nếu không có thì trả về.Ngược lại độ dài bé hơn max_length thì trả về 
        batch_inputs = []
        # batch_map = []  # Mỗi phần tử là (q_idx, p_idx)
        # new_graph_state = {"questions": []}
        new_graph_state = deepcopy(state)
        # Tạo batch_inputs cho LLM
        for q_idx, question in enumerate(new_graph_state["questions"]):
            question_content = question["question_content"]
            # Lấy metadata từ đối tượng, nếu không có thì trả về None
            question_metadata = getattr(question_content, "metadata", None)
            # print(f"question_metadata {question_metadata}")
            metadata_parts = []
            # Sử dụng getattr để lấy thuộc tính nếu tồn tại
            chapter = question_metadata["chapter_number"] if question_metadata["chapter_number"] else None
            if chapter:
                metadata_parts.append(f"current chapter: {chapter}")
            article = question_metadata["article_number"] if question_metadata["article_number"] else None
            if article:
                metadata_parts.append(f"current article: {article}")
            clause = question_metadata["clause_number"] if question_metadata["clause_number"] else None
            if clause:
                metadata_parts.append(f"current clause: {clause}")
            sub_clause = question_metadata["sub_clause_number"] if question_metadata["sub_clause_number"] else None
            if sub_clause:
                metadata_parts.append(f"current sub-clause: {sub_clause}")
            entry = {"document": question_content.page_content}
            entry["metadata"] = ", ".join(metadata_parts)
            # print(entry)
            batch_inputs.append(entry)
            
        responses = self.extract_reference_generator.batch(batch_inputs) if batch_inputs else []
        responses =retry_failed_batches(batch_inputs,responses,self.extract_reference_generator)
        
        # new_graph_state = {"questions": []}
        count=0
        questions=[]
        # Tạo state mới
        for q_idx, question in enumerate(new_graph_state["questions"]):
                new_question = question.copy()
                new_question["direct_reference"]=[]
                new_question["direct_reference_index"]=[]
                new_question["direct_reference_text"]=[]
                response = responses[q_idx]
                # print(f"response {response}")
                if response['has_reference'] == "yes" and response["is_extractable"] == "yes":
                    # print("=========================")
                    # print(f"response {response}")
                    # print(f"""question {question}""")
                    for reference in response["references"]:
                        if reference["resolved"]["Chapter"]==-1 and reference["resolved"]["Article"]==-1 and reference["resolved"]["clause"]==-1 and reference["resolved"]["sub_clause"]==-1:
                            continue
                        count+=1
                        # teee="No"

                        #####
                
                    
                        resolved = reference["resolved"]
                        metadata = question["question_content"].metadata

                        if resolved["sub_clause"] != -1:
                            resolved["clause"] = resolved["clause"] if resolved["clause"] != -1 else metadata["clause_number"]
                            resolved["Article"] = resolved["Article"] if resolved["Article"] != -1 else metadata["article_number"]

                        if resolved["clause"] != -1 and resolved["Article"] == -1:
                            resolved["Article"] = metadata["article_number"]
                        # print(f"resolved {resolved}")
                        for ref_q_index,ref_q in enumerate(state["questions"]):
                            if reference["resolved"]["Article"]!=-1:
                                if (reference["resolved"]["Article"]==-1 or ref_q["question_content"].metadata["article_number"] == str(reference["resolved"]["Article"])) and \
                                (reference["resolved"]["clause"]==-1 or ref_q["question_content"].metadata["clause_number"] == str(reference["resolved"]["clause"])) and \
                                (reference["resolved"]["sub_clause"]==-1 or ref_q["question_content"].metadata["sub_clause_number"] == str(reference["resolved"]["sub_clause"])) :
                                    new_question["direct_reference"].append(ref_q["question_content"])
                                    new_question["direct_reference_index"].append(ref_q_index)
                                    teee="yes"
                            else:
                                if (reference["resolved"]["Chapter"]==-1 or ref_q["question_content"].metadata["chapter_number"] == str(reference["resolved"]["Chapter"])) and \
                                (reference["resolved"]["Article"]==-1 or ref_q["question_content"].metadata["article_number"] == str(reference["resolved"]["Article"])) and \
                                (reference["resolved"]["clause"]==-1 or ref_q["question_content"].metadata["clause_number"] == str(reference["resolved"]["clause"])) and \
                                (reference["resolved"]["sub_clause"]==-1 or ref_q["question_content"].metadata["sub_clause_number"] == str(reference["resolved"]["sub_clause"])) :
                                    new_question["direct_reference"].append(ref_q["question_content"])
                                    new_question["direct_reference_index"].append(ref_q_index)
                                    teee="yes"
                        if new_question["direct_reference"]:
                        # print(f"""batch_inputs: {batch_inputs[q_idx]}""")
                        # print(f"""reference["resolved"] {reference["resolved"]}""")
                            direct_reference_text=get_reftext(reference["resolved"])
                            new_question["direct_reference_text"]=direct_reference_text

                        # if teee=="No":
                        #     print("|||||||||||||||||||||")
                        #     print(f"response {response}")
                        #     print(f"""question {question}""")
                questions.append(new_question)
                new_graph_state["processed_question_index"]=[]
        new_graph_state["questions"]=questions
        # print(f"count {count}")
        return new_graph_state
    
    def grade_direct_reference(self, state):
        """
        Kiểm tra direct_reference của mỗi câu hỏi:
        - Chỉ thực hiện nếu ít nhất một câu hỏi có hơn 1 direct_reference.
        - Dùng model để kiểm tra độ liên quan của direct_reference.
        - Cập nhật lại graph state với direct_reference đã được lọc.
        """
        print("---GRADE REFERENCE---")
        new_graph_state = deepcopy(state)  # Tạo bản sao để tránh sửa đổi trực tiếp

        batch_inputs = []
        batch_indicates = []
        has_multiple_references = False  # Cờ kiểm tra có câu hỏi nào có >1 reference không

        # Thu thập dữ liệu batch
        for q_idx, question in enumerate(state["questions"]):
            if len(question.get("direct_reference_text", [])) > 1:
                has_multiple_references = True
                for r_idx, direct_reference_text in enumerate(question["direct_reference_text"]):
                    batch_inputs.append({
                        "main_text": question["question_content"].page_content,
                        "referenced_text": direct_reference_text["text"]
                    })
                    batch_indicates.append((q_idx, r_idx))

        # Nếu không có câu hỏi nào có >1 direct_reference, thoát sớm
        if not has_multiple_references:
            print("NOTHING TO GRADE")
            return state

        # Chạy mô hình kiểm tra tính liên quan
        responses =self.sematic_reference_generator.batch(batch_inputs) if batch_inputs else []
        responses =retry_failed_batches(batch_inputs,responses,self.sematic_reference_generator)
        # Ánh xạ kết quả vào new_graph_state
        result_map = {batch_indicates[i]: responses[i]["provide_additional_meaning"].strip().lower() == "yes"
                        for i in range(len(responses))}

        for q_idx, question in enumerate(new_graph_state["questions"]):
            if len(question.get("direct_reference_text", [])) > 1:
                # Lọc lại danh sách direct_reference dựa trên kết quả kiểm tra
                question["direct_reference_text"] = [
                    ref for r_idx, ref in enumerate(question["direct_reference_text"])
                    if result_map.get((q_idx, r_idx), False)  # Chỉ giữ lại ref nếu is_related == "yes"
                ]
        for q_idx, question in enumerate(new_graph_state["questions"]):
            new_index_list = []
            for direct_reference_text in question["direct_reference_text"]:
                new_index_list.extend(direct_reference_text["index_list"])
            question["direct_reference_index"]=new_index_list

        return new_graph_state

    def rewrite_question_content(self, state):
        """
        Lặp qua từng câu hỏi và tạo batch_inputs để cập nhật lại nội dung câu hỏi:
        - Với mỗi câu hỏi, tạo batch_inputs chứa {"main_section": question["question_content"], "refer_sections": direct_reference_text}.
        - Chạy batch qua mô hình để tạo câu hỏi rewrite.
        - Lưu kết quả vào question["rewrite_question_content"], là một list.
        """
        print("---REWRITE QUESTION CONTENT---")
        new_graph_state = deepcopy(state)  # Sao chép tránh sửa đổi trực tiếp
        batch_inputs = []
        batch_indicates = []
        # Thu thập dữ liệu batch
        for q_idx, question in enumerate(state["questions"]):
            new_graph_state["questions"][q_idx]["rewrite_question_content"] = []
            for direct_reference_text in question.get("direct_reference_text", []):
                batch_inputs.append({
                    "main_section": question["question_content"].page_content,
                    "refer_sections": direct_reference_text["text"]
                })
                batch_indicates.append(q_idx)
        # Nếu không có dữ liệu nào để xử lý, thoát sớm
        if not batch_inputs:
            print("NO QUESTIONS TO REWRITE")
            return state
        
        # Chạy mô hình sinh câu hỏi rewrite
        responses = self.rewrite_clause_generator.batch(batch_inputs) if batch_inputs else []
        responses =retry_failed_batches(batch_inputs,responses, self.rewrite_clause_generator)
        # Cập nhật kết quả vào new_graph_state
        for i, q_idx in enumerate(batch_indicates):
            new_graph_state["questions"][q_idx]["rewrite_question_content"].append(responses[i]["generated_section"])
        return new_graph_state

    def loopback_node(self, graph_state):
        print("--- LOOPBACK NODE ---")
        new_graph_state = deepcopy(graph_state)  # Tạo bản sao sâu để tránh sửa đổi trực tiếp vào state gốc
        processed_question_index = graph_state["processed_question_index"]
        next_batch = []
        current_batch =[]
        direct_count=0
        ref_count=0
        for index, question in enumerate(graph_state["questions"]):
            if index not in processed_question_index:
                if len(question["direct_reference_text"])==0:
                    current_batch.append(index)
                    direct_count+=1
                elif all(ref_q in processed_question_index for ref_q in question["direct_reference_index"]):
                    current_batch.append(index)
                    ref_count+=1
                else:
                    next_batch.append(index)  # Chưa đủ điều kiện chạy
        print(f"direct count {direct_count}")
        print(f"ref count {ref_count}")
        new_graph_state["current_question_index"]=current_batch
        return new_graph_state


    def create_propositions(self, graph_state):
        print("---CREATE PROPOSITIONS---")
        new_graph_state = deepcopy(graph_state)  # Tạo bản sao sâu để tránh sửa đổi trực tiếp vào state gốc
        direct_batch_inputs = []
        ref_batch_inputs = []
        direct_batch_map = []
        ref_batch_map = []
        print(f"""len(graph_state["current_question_index"]) {len(graph_state["current_question_index"])}""")
        count=0
        for index, question in enumerate(graph_state["questions"]):
            if index in graph_state["current_question_index"]:
                if len(question["direct_reference_text"])==0:
                    # count+=1
                    direct_batch_inputs.append({"document": question["question_content"].page_content})  # Chạy hàm proposition_gen
                    direct_batch_map.append(index)
                elif  all(ref_q in graph_state["processed_question_index"] for ref_q in question["direct_reference_index"]):
                    count+=1
                    for context in question["rewrite_question_content"]:
                        ref_batch_inputs.append({"document": context})
                        ref_batch_map.append(index)
                else:
                    print("what the fuck ")
        print(f"len(direct ) {len(direct_batch_inputs)}")
        print(f"len(ref ) {len(ref_batch_inputs)}")
        print(f"count {count}")
        # Chạy batch proposition
        direct_proposition_responses = self.proposition_generator.batch(direct_batch_inputs)
        direct_proposition_responses =retry_failed_batches(direct_batch_inputs,direct_proposition_responses,self.proposition_generator)

        ref_proposition_responses = self.proposition_generator.batch(ref_batch_inputs)
        ref_proposition_responses =retry_failed_batches(ref_batch_inputs,ref_proposition_responses,self.proposition_generator)
        # print(f"direct_proposition_responses {direct_proposition_responses}")
        for i, proposition_response in enumerate(direct_proposition_responses):
            propositions = [
                {
                    "proposition_content": prop["proposition"],
                    "documents": [],
                    "filtered_documents": []
                }
                for prop in proposition_response['propositions']
            ]
            new_graph_state["questions"][direct_batch_map[i]]["propositions"] = propositions
            new_graph_state["processed_question_index"].append(direct_batch_map[i])
        for i, proposition_response in enumerate(ref_proposition_responses):
            propositions = [
                {
                    "proposition_content": prop["proposition"],
                    "documents": [],
                    "filtered_documents": []
                }
                for prop in proposition_response['propositions']
            ]
            new_graph_state["questions"][ref_batch_map[i]]["ref_propositions"] = propositions
            new_graph_state["processed_question_index"].append(ref_batch_map[i])

        return new_graph_state

    def retrieve(self, state):
        print("---RETRIEVE---")
        new_graph_state = deepcopy(state)  # Tạo bản sao sâu để tránh sửa đổi trực tiếp vào state gốc
        count=0
        for index, question in enumerate(new_graph_state["questions"]):
        # for question in new_graph_state["questions"]:
            if index in new_graph_state["current_question_index"]:
                for p_idx, proposition in enumerate(question["propositions"]):
                    retrieved_docs = self.retriever.invoke(proposition["proposition_content"])
                    question["propositions"][p_idx]["documents"] = retrieved_docs  # Cập nhật trực tiếp vào bản sao mới
                    count+=1
                for p_idx, proposition in enumerate(question["ref_propositions"]):
                    retrieved_docs = self.retriever.invoke(proposition["proposition_content"])
                    question["ref_propositions"][p_idx]["documents"]= retrieved_docs
                    count+=1
        print(f"---have retrieved for {count} propositions---")
        new_graph_state["rewrite_count"]=0
        return new_graph_state

    def grade_documents(self, state):
        """
        Đánh giá và lọc bỏ các tài liệu không liên quan cho những proposition có filtered_documents == [].
        Những proposition đã có filtered_documents (không rỗng) sẽ được giữ nguyên.

        Args:
            state (Dict): Graph state chứa danh sách các câu hỏi và propositions.
        
        Returns:
            Dict: Graph state mới với các proposition đã được cập nhật filtered_documents.
        """
        print("---GRADE DOCUMENTS---")
        new_graph_state = deepcopy(state)  # Tạo bản sao sâu để tránh sửa đổi trực tiếp vào state gốc
        batch_inputs = []
        batch_map = []  # Mỗi phần tử là (q_idx, p_idx, is_ref, doc_idx)
        for q_idx, question in enumerate(new_graph_state["questions"]):
            # Xử lý propositions thông thường
            if q_idx in new_graph_state["current_question_index"]:
                for p_idx, proposition in enumerate(question["propositions"]):
                    if proposition.get("filtered_documents", []):
                        continue
                    for doc_idx, doc in enumerate(proposition["documents"]):
                        
                        batch_inputs.append({
                            "context": doc.page_content,
                            "contract": proposition["proposition_content"]
                        })
                        batch_map.append((q_idx, p_idx, -1, doc_idx))  # is_ref = 0
                
                for ref_p_idx, proposition in enumerate(question.get("ref_propositions", [])):
                    if proposition.get("filtered_documents", []):
                        continue
                    for doc_idx, doc in enumerate(proposition["documents"]):
                        batch_inputs.append({
                            "context": doc.page_content,
                            "contract": proposition["proposition_content"]
                        })
                        batch_map.append((q_idx, -1, ref_p_idx, doc_idx))  # is_ref = 1
            
        # Gọi batch processing nếu có input; nếu không có, responses là danh sách rỗng
        responses = self.retrieval_grader.batch(batch_inputs) if batch_inputs else []
        responses =retry_failed_batches(batch_inputs,responses,self.retrieval_grader)
        count=0
        # Cập nhật new_graph_state với kết quả đánh giá
        for q_idx, question in enumerate(new_graph_state["questions"]):
            if q_idx in new_graph_state["current_question_index"]:
                for p_idx, proposition in enumerate(question["propositions"]):
                    if proposition.get("filtered_documents", []):
                        continue
                    filtered_docs = []
                    for map_idx, (mq, mp, m_ref, md) in enumerate(batch_map):
                        if mq == q_idx and mp == p_idx and m_ref == -1:
                            response = responses[map_idx]["binary_score"].strip() if responses else ""
                            if response.lower() == "yes":
                                filtered_docs.append(proposition["documents"][md])
                    proposition["filtered_documents"] = filtered_docs
                    count+= len(filtered_docs)
                for ref_p_idx, proposition in enumerate(question.get("ref_propositions", [])):
                    if proposition.get("filtered_documents", []):
                        continue
                    filtered_docs = []
                    for map_idx, (mq, mp, m_ref, md) in enumerate(batch_map):
                        if mq == q_idx and mp == -1 and ref_p_idx == mp:
                            response = responses[map_idx]["binary_score"].strip() if responses else ""
                            if response.lower() == "yes":
                                filtered_docs.append(proposition["documents"][md])
                    proposition["filtered_documents"] = filtered_docs
                    count+= len(filtered_docs)
        print(f"---have filtered and have {count} docs left---")
        return new_graph_state

    def generate(self, state):
        def docs2text(docs):
            return '\n'.join([doc.page_content for doc in docs])
            
        def question2text(question):
            return f"""第{question.metadata["chapter_number"]}章　{question.metadata["chapter_title"]} \n 第{question.metadata["article_number"]}条（{question.metadata["article_title"]}）\n{question.page_content}"""
        
        print("---GENERATE---")
        new_graph_state = deepcopy(state)
        batch_doc_inputs = []
        batch_both_inputs = []
        batch_doc_indices = []
        batch_both_indices = []
        print(f"""current_question_index {new_graph_state["current_question_index"]}""")
        
        for q_idx, question in enumerate(new_graph_state["questions"]):
            if q_idx in new_graph_state["current_question_index"]:
                doc_list = set()  # Dùng set để loại bỏ tài liệu trùng lặp
                for p_idx, proposition in enumerate(question["propositions"]):
                    if proposition["filtered_documents"]:
                        doc_list.update(str(proposition["filtered_documents"]))
                
                if len(question["direct_reference_text"])!=0:
                    for ref_p_idx, proposition in enumerate(question["ref_propositions"]):
                        if proposition["filtered_documents"]:
                            doc_list.update(str(proposition["filtered_documents"]))
                    doc_list=[Document(doc) for doc in doc_list]
                    if doc_list:
                        batch_both_inputs.append({
                            "context": docs2text(doc_list),
                            "contract": question2text(question["question_content"]),
                            "new_query": question["rewrite_question_content"][0]
                        })
                        batch_both_indices.append(q_idx)
                    else:
                        question["generation"] = """{"evaluation":"insufficient_information",
                        "explanation":"CANNOT FIND ANY RELEVANT DOCUMENT"}"""
                else:
                    doc_list=[Document(doc) for doc in doc_list]
                    if doc_list:
                        batch_doc_inputs.append({
                            "context": docs2text(doc_list),
                            "contract": question2text(question["question_content"])
                        })
                        batch_doc_indices.append(q_idx)
                    else:
                        question["generation"] = """{"evaluation":"insufficient_information",
                        "explanation":"CANNOT FIND ANY RELEVANT DOCUMENT"}"""
        print("start both")
        both_responses = self.rag_chain_both.batch(batch_both_inputs)
        both_responses = retry_failed_batches(batch_both_inputs, both_responses, self.rag_chain_both)
        print("end both")
        print("start doc")
        
        doc_responses = self.rag_chain_doc.batch(batch_doc_inputs)
        doc_responses = retry_failed_batches(batch_doc_inputs, doc_responses, self.rag_chain_doc)
        print("end doc")
        
        for idx, response in enumerate(both_responses):
            q_idx = batch_both_indices[idx]
            new_graph_state["questions"][q_idx]["generation"] = response
        
        for idx, response in enumerate(doc_responses):
            q_idx = batch_doc_indices[idx]
            new_graph_state["questions"][q_idx]["generation"] = response
        
        return new_graph_state
    
    def query_transformation(self, state):
        print("---QUERY TRANSFORMATION---")
        # print(f"graph_state {state}")
        propositions_to_recheck = []
        count = 0
        # 1. Chuẩn bị input cho query transformation
        query_transformation_input = [
            {"query": prop_data["original_proposition"]["proposition_content"]}
            for prop_data in state["propositions_to_rewrite"]
        ]

        # 2. Gọi query transformation
        transformed_queries = self.query_transformation_generator.batch(query_transformation_input)
        transformed_queries =retry_failed_batches(query_transformation_input,transformed_queries,self.query_transformation_generator)
        print("---trieve---")
        # 3. Xử lý retrieval từng query một
        prop_documents = {
            prop_data["original_proposition"]["proposition_content"]: {}
            for prop_data in state["propositions_to_rewrite"]
        }
        
        for i, transformed_query in enumerate(transformed_queries):
            original_prop = query_transformation_input[i]["query"]
            queries = (
                transformed_query["paraphrased_queries"]
                + transformed_query["detailed_queries"]
                + transformed_query["generalized_queries"]
                + transformed_query["expanded_queries"]
            )
            for query in queries:
                retrieved_docs = self.retriever.invoke(query)  # Chạy tuần tự từng query

                for doc in retrieved_docs:
                    # Dùng doc.page_content làm key, và lưu đối tượng document đầy đủ
                    prop_documents[original_prop][doc.page_content] = doc

        # 4. Cập nhật lại graph_state với các documents mới
        updated_state = deepcopy(state)
        old_docs_keys = set()
        for prop_data in state["propositions_to_rewrite"]:
            for d in prop_data["original_proposition"].get('documents', []):
                old_docs_keys.add(d.page_content)

        for prop_data in updated_state["propositions_to_rewrite"]:
            q_idx = prop_data["question_index"]
            p_idx = prop_data["proposition_index"]
            ref_p_idx = prop_data["ref_propositions_index"]
            proposition_text = prop_data["original_proposition"]["proposition_content"]

            new_docs_dict = {
                key: doc for key, doc in prop_documents[proposition_text].items()
                if key not in old_docs_keys
            }
            new_documents = list(new_docs_dict.values())
            count+=len(new_documents)
            # print("len new docs",len(new_documents))
            if new_documents:
                if p_idx!=-1:
                    updated_state["questions"][q_idx]["propositions"][p_idx]["documents"] = new_documents
                else:
                    updated_state["questions"][q_idx]["ref_propositions"][ref_p_idx]["documents"] = new_documents
                # print(updated_state["questions"][q_idx]["propositions"][p_idx])
            else:
                if p_idx!=-1:
                    propositions_to_recheck.append(updated_state["questions"][q_idx]["propositions"][p_idx])
                else:
                    propositions_to_recheck.append(updated_state["questions"][q_idx]["ref_propositions"][ref_p_idx])
        if not updated_state.get("rewrite_count", 0):  # Mặc định là 0 nếu không có
            updated_state["rewrite_count"] = 1
        else:
            updated_state["rewrite_count"] += 1
        updated_state["propositions_to_rewrite"]=[]
        print(f"---new docs num: {count}")
        return updated_state


    def check_empty_propositions(self, state):
        print("---CHECK EMPTY PROPOSITIONS---")
        new_graph_state = deepcopy(state)  # Tạo bản sao sâu để tránh sửa đổi trực tiếp vào state gốc

        propositions_to_rewrite = []  # Danh sách propositions cần rewrite
        count = 0
        
        for q_idx, question in enumerate(state["questions"]):
            if q_idx in new_graph_state["current_question_index"]:
                for p_idx, proposition in enumerate(question["propositions"]):
                    if not proposition["filtered_documents"]:  # Nếu danh sách documents rỗng
                        count+=1
                        propositions_to_rewrite.append({
                            "question_index": q_idx,  # Lưu vị trí question
                            "proposition_index": p_idx,  # Lưu vị trí proposition
                            "ref_propositions_index": -1,  # Lưu vị trí proposition
                            "original_proposition": proposition,  # Lưu thông tin gốc
                        })
                for ref_p_idx, proposition in enumerate(question["ref_propositions"]):
                    if not proposition["filtered_documents"]:  # Nếu danh sách documents rỗng
                        count+=1
                        propositions_to_rewrite.append({
                            "question_index": q_idx,  # Lưu vị trí question
                            "proposition_index": -1,  # Lưu vị trí proposition
                            "ref_propositions_index": ref_p_idx,  # Lưu vị trí proposition
                            "original_proposition": proposition,  # Lưu thông tin gốc
                        })        
        print(f"---{count}--- propositions that can not find documents")
        new_graph_state["propositions_to_rewrite"]=propositions_to_rewrite
        return new_graph_state

    def should_create_proposition(self, graph_state):
        """Kiểm tra xem có cần chạy create_proposition không."""
        if len(graph_state["current_question_index"]) != 0:  # True nếu có câu hỏi có thể chạy
            print("STILL HAVE INDEPENDENT CHUNK")
            return "STILL HAVE INDEPENDENT CHUNK"
        else:
            print("NO INDEPENDENT CHUNK")
            return "NO INDEPENDENT CHUNK"
