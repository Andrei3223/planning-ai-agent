import os

from langchain_openai import ChatOpenAI

from dotenv import load_dotenv

################ ENV ################

load_dotenv()
MODEL_NAME = os.getenv("MODEL_NAME")
API_KEY= os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")

llm = ChatOpenAI(
    model=MODEL_NAME,
    temperature=0,
    api_key=API_KEY,
    base_url=BASE_URL,
)