import json
from my_utils import normalize_dict
from processor import label_and_parse_text_from_content
from langchain_core.documents import Document
from langchain_community.llms.vllm import VLLM
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.runnables import RunnableConfig
from GraphRAG import GraphRAG
from ModuleRAG import ModuleRAG
from ModuleRetrieval import ModuleRetrieval

class RAGPipeline:
    def __init__(self, vllm_model_path, data_path_retrieval):
        self.config = RunnableConfig(recursion_limit=50)
        # Tạo VLLM model
        vllm_model = VLLM(
            model=vllm_model_path,
            tensor_parallel_size=1,
            n=1,
            presence_penalty=0.0,
            frequency_penalty=0.0,
            temperature=0.7,
            top_p=0.6,
            top_k=20,
            stop=None,
            ignore_eos=False,
            max_new_tokens=2048,
            logprobs=None,
            download_dir=None,
            vllm_kwargs={
                "quantization":"gptq",
                "max_model_len": 3036,
                "gpu_memory_utilization":0.5
            }
        )
        # Tạo moduleRAG
        moduleRAG = ModuleRAG(vllm_model)
        moduleRetrieval = ModuleRetrieval(data_path_retrieval)
        
        # Khởi tạo app
        graphRAG = GraphRAG(
            extract_reference_generator = moduleRAG.get_extract_reference_generator(),
            sematic_reference_generator = moduleRAG.get_sematic_reference_generator(),
            rewrite_clause_generator = moduleRAG.get_rewrite_clause_generator(),
            proposition_generator = moduleRAG.get_proposition_generator(),
            retriever = moduleRetrieval.get_module(),
            retrieval_grader = moduleRAG.get_retrieval_grader(),
            rag_chain_both = moduleRAG.get_rag_chain_both(),
            rag_chain_doc = moduleRAG.get_rag_chain_doc(),
            query_transformation_generator = moduleRAG.get_query_transformation_generator()
        )
        self.app = graphRAG.get_app()

    def processing(self, file_content):
        json_output, root_text = label_and_parse_text_from_content(file_content)
        return json_output, root_text
    
    def create_graph_state(self, json_output, root_text):
        # Chuẩn hóa dữ liệu
        normalized_data= normalize_dict(json_output)
        # Chuyển thành json
        normalized_data_json = json.loads(normalized_data)
        # Lấy số chương cần xử lý
        print("Docs have ",len(normalized_data_json['chapters']),"chapters")
        useful_data = {'chapters':normalized_data_json['chapters'][:3]}
        print("We using 3 first chapters")
        docs_list = [
            Document(
                page_content=sub_clause.get("sub_clause_content") if sub_clause else clause["clause_title"],
                metadata={
                    "chapter_title": chapter['chapter_title'],
                    "chapter_number": chapter['chapter_number'],
                    # "chapter_text": chapter['chapter_text'],
                    "article_title": article['article_title'], 
                    "article_number": article['article_number'],
                    # "article_text": article['article_text'],
                    "clause_number": clause['clause_number'],
                    "clause_title": clause["clause_title"],
                    # "clause_text": clause["clause_content"],
                    "sub_clause_number": sub_clause.get("sub_clause_number") if sub_clause else "",
                    "sub_clause_content": sub_clause.get("sub_clause_content") if sub_clause else "",

                    # "clause_content":  clause['clause_title']+"\n" if clause['clause_content'] else "",
                    
                }
            )
            for chapter in useful_data['chapters'] 
            for article in chapter['articles']
            for clause in article['clauses']
            for sub_clause in (clause["sub_clauses"] or [None])  # Nếu rỗng thì tạo danh sách chứa None
        ]
        # Split
        text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=500, chunk_overlap=30
        )

        doc_splits = text_splitter.split_documents(docs_list)
        for i, doc in enumerate(doc_splits):
            doc.metadata['chunk_id'] = i+1 ### adding chunk id

        graph_state = {"questions":
                    [
                        {"question_content":Document(
                            page_content=doc_split.metadata['clause_title'] +"\n"+ doc_split.page_content if doc_split.metadata['sub_clause_content'] else doc_split.page_content,
                            metadata={
                                "chapter_title": doc_split.metadata['chapter_title'],
                                "chapter_number": doc_split.metadata['chapter_number'],
                                # "chapter_text": doc_split.metadata['chapter_text'],
                                "article_title": doc_split.metadata['article_title'], 
                                "article_number": doc_split.metadata['article_number'],
                                # "article_text": doc_split.metadata['article_text'],
                                "clause_number": doc_split.metadata['clause_number'],
                                "clause_title": doc_split.metadata['clause_title'],
                                # "clause_text": doc_split.metadata['clause_text'],
                                "sub_clause_number": doc_split.metadata['sub_clause_number'],
                                "sub_clause_content": doc_split.metadata['sub_clause_content'],
                            }),
                        "propositions":[],
                        "ref_propositions":[]}
        for doc_split in doc_splits],
                        "root_text":root_text}
        return graph_state
        
    def run(self, file_content):
        # Xử lý dữ liệu thành cấu trúc JSON và root_text
        json_output, root_text = self.processing(file_content)
        
        # Tạo graph state
        graph_state = self.create_graph_state(json_output, root_text)
        
        final_state = self.app.invoke(graph_state,config=self.config)

        return final_state

if __name__=="__main__":
    print("Hello World")

    
    # Khởi tạo các biến cần thiết
    vllm_model_path = "/home/trung/RAG_ADVANCED/Qwen2.5-14B-Instruct-GPTQ-Int4"
    data_path_retrieval = "/home/trung/RAG_ADVANCED/full_corpus_110225_with_metadata.json"
    # Khởi tạo RAG pipeline
    rag_pipeline = RAGPipeline(vllm_model_path=vllm_model_path, data_path_retrieval=data_path_retrieval)
    # Đọc dữ liệu file txt cần xử lý
    input_file = "./text_file1_3chapters.txt"
    with open(input_file, 'r', encoding='utf-8') as infile:
        file_content = infile.read()

    # Truyền dữ liệu vào pipeline
    output_data = rag_pipeline.run(file_content)
    # Xuất kết quả
