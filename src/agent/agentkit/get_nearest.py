import os
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

load_dotenv(override=True)


def load_chroma_retriever(persist_directory: str = "./DBs/RAG", k: int = 5):
    """
    Loads a previously persisted Chroma vector store and returns a retriever.
    """
    embedding_model = OpenAIEmbeddings(
        model=os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
        api_key=os.getenv('OPENAI_API_KEY_KIRILL'),
    )

    vector_store = Chroma(
        persist_directory=persist_directory,
        embedding_function=embedding_model
    )

    retriever = vector_store.as_retriever(search_kwargs={"k": k})
    return retriever


def get_nearest_events(query: str, persist_directory: str = "./DBs/RAG", k: int = 5):
    """
    Retrieves the top-k most similar documents from the Chroma vector store
    without involving the LLM.

    Args:
        query (str): Text query describing what to look for.
        persist_directory (str): Path to Chroma DB.
        k (int): Number of documents to retrieve.

    Returns:
        List[Dict]: Each dict contains 'content', 'metadata', and 'score'.
    """
    retriever = load_chroma_retriever(persist_directory=persist_directory, k=k)

    # Perform the similarity search directly on the vector store retriever
    docs = retriever.vectorstore.similarity_search_with_score(query, k=k)
    
    results = []
    for doc, score in docs:
        results.append({
            "content": doc.page_content,
            "metadata": doc.metadata,
            "score": score,
        })

    return results
