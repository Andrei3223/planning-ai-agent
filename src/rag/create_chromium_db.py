import os
import ast
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma


def dict_to_langchain_document(data_dict: dict) -> Document:
    """
    Converts a single dictionary record into a LangChain Document.
    """
    page_content = (
        f"Title: {data_dict.get('title', 'N/A')}. "
        f"Date: {data_dict.get('date', 'N/A')}. "
        f"URL: {data_dict.get('url', 'N/A')}"
    )
    
    metadata = {
        "source_url": data_dict.get('url'),
        "event_title": data_dict.get('title'),
        "event_date": data_dict.get('date')
    }
    
    return Document(page_content=page_content, metadata=metadata)


def create_chromium_db(file_path: str = "src/rag/data/data.txt", persist_directory: str = "DBs/RAG"):
    """
    Reads a text file containing one or more Python-style dictionaries,
    converts them into LangChain Documents, and stores them in a Chroma DB.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        raw_lines = [line.strip() for line in file if line.strip()]
    
    data_list = []
    for i, line in enumerate(raw_lines):
        try:
            record = ast.literal_eval(line)
            if isinstance(record, dict):
                data_list.append(record)
            else:
                print(f"Line {i+1} is not a dict, skipping.")
        except Exception as e:
            print(f"Failed to parse line {i+1}: {e}")

    if not data_list:
        raise ValueError("No valid dictionary records found in file.")

    print(f"Parsed {len(data_list)} event records from file.")

    langchain_documents = [dict_to_langchain_document(d) for d in data_list]

    embedding_model = OpenAIEmbeddings(
        model='text-embedding-3-small',
        api_key=os.getenv('OPENAI_API_KEY_KIRILL')
    )

    vector_store = Chroma.from_documents(
        documents=langchain_documents,
        embedding=embedding_model,
        persist_directory=persist_directory
    )

    retriever = vector_store.as_retriever(search_kwargs={"k": 5, "score_threshold": 0.1}) 
    print("ChromaDB indexing complete.")
    return retriever

