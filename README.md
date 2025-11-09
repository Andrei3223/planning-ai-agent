# Event Recommender AI Agent


This project is designed to find relevant and suitable events for a **group of people**. It utilizes **LangChain** with several **OpenAI models** and a **RAG (Retrieval-Augmented Generation)** platform for efficient event retrieval. A **Telegram bot** is used as the base UI.

## Features

- **AI-Powered Planning**: Uses OpenAI's language models for intelligent decision-making and planning.
- **Vector Search (RAG)**: Implements **Chroma** for vector-based event retrieval, ensuring recommendations are contextually relevant.
- **Customizable**: Easily configurable via environment variables for different models and APIs.
- **Persistent Storage**: Supports persistent storage of vector embeddings (Chroma) and other necessary data (SQLite) for efficient retrieval and state management.

## Prerequisites

- Python 3.8 or higher
- OpenAI API key
- Required Python libraries (see `requirements.txt`)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/planning-ai-agent.git
   cd planning-ai-agent

2. Create a virtual environment:

    `python3 -m venv venv`

3. Activate is:

    `source venv/bin/activate`

4. Install dependencies:

    `pip install -r requirements.txt`

5. Set up evironment.

    Create a .env file in the root directory:
    ```bash
    TELEGRAM_BOT_TOKEN="[YOUR-TG-TOKEN]"

    MODEL_NAME = "gpt-5-nano"
    BASE_URL = "[YOUR-MODEL-BASE-URL]"
    API_KEY = "[YOUR-OPENAI-API-KEY]"

    EMBEDDING_MODEL="text-embedding-3-small"

    DEBUG_GRAPH = False
    DB_PATH_EVENTS=events.sqlite
    DB_PATH_BUSYHOURS=busyhours.sqlite
    DB_PATH_USERS=users.sqlite
    ```

6. Run project:
    `python3 src/bot.py `


## Project Structure

    planning-ai-agent/
    ├── data/                   # Data files and Chroma vector store (DBs, vector data)
    ├── src/                    # All source code (including bot.py)
    ├── requirements.txt        # Python dependencies
    ├── .env                    # Environment variables
    ├── README.md               # Project documentation
    └── LICENSE                 # MIT License file

## License

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](/LICENSE)