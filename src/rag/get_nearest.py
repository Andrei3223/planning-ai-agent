import os
from dotenv import load_dotenv
from datetime import datetime
from langchain_openai import OpenAI, OpenAIEmbeddings
from langchain_classic.chains import RetrievalQA
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI



load_dotenv(override=True)


def load_chroma_retriever(persist_directory: str = "./data/chroma_store"):
    """
    Loads a previously persisted Chroma vector store and returns a retriever.
    """
    embedding_model = OpenAIEmbeddings(
        model=os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
        api_key=os.getenv('OPENAI_API_KEY_KIRILL'),
    )

    # Load the existing Chroma DB
    vector_store = Chroma(
        persist_directory=persist_directory,
        embedding_function=embedding_model
    )

    # Create retriever with default search settings
    retriever = vector_store.as_retriever(
        search_kwargs={"k": 5}
    )

    print("Retriever loaded from Chroma DB.")
    return retriever

def get_nearest_events(query: str):
    retriever = load_chroma_retriever()

    llm = ChatOpenAI(
        model_name=os.getenv("MODEL", "gpt-5-nano"),
        # base_url=os.getenv('API_URL'),
        api_key=os.getenv('OPENAI_API_KEY_KIRILL'),
        temperature=0.0,
        # api_key=os.getenv('OPENAI_API_KEY')
    )
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        # return_source_documents=True,  # optional, if you want to see which docs were used
    )

    
    result = qa_chain.run(query)

    return result


if __name__ == "__main__":
    query = "Tell me about the most recent events related to AI."
    response = get_nearest_events(query)
    print(response)
