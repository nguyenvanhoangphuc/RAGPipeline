import json
import hashlib
from langchain.vectorstores import Chroma
from langchain_core.documents import Document
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter

class ModuleRetrieval:
    def __init__(self, data_path):
        with open(data_path, "r", encoding="utf-8") as f:
            data_docs = json.load(f)


        docs = []
        for doc in data_docs:
            docs.append(
                Document(
                    page_content=doc["content"],
                    metadata=doc["metadata"]
                )
            )

        unique_documents = []
        seen = set()

        for document in docs:
            # Truy cập metadata và content từ đối tượng Document
            metadata = document.metadata
            content = document.page_content
            
            # Chuyển đổi metadata và content thành chuỗi JSON để so sánh
            doc_str = json.dumps({"metadata": metadata, "content": content}, sort_keys=True)
            
            # Tạo một hash MD5 cho chuỗi JSON này
            doc_hash = hashlib.md5(doc_str.encode('utf-8')).hexdigest()
            
            # Nếu tài liệu chưa gặp, thêm vào list unique_documents
            if doc_hash not in seen:
                unique_documents.append(document)
                seen.add(doc_hash)

        # Kết quả là danh sách không có phần tử lặp
        print("len unique_documents",len(unique_documents))
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=30)
        chunks = text_splitter.split_documents(unique_documents)
        embedding_function = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-large")

        vector_store = Chroma.from_documents(
            documents=chunks,
            embedding=embedding_function,
            persist_directory="vectorDB")# lưu ý cái này sẽ lưu đè

        self.retriever = vector_store.as_retriever(search_kwargs={"k": 10})

    def get_module(self):
        return self.retriever