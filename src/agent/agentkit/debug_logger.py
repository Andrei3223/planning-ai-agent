import os 
import json
from dotenv import load_dotenv

load_dotenv()
DEBUG_GRAPH = os.getenv("DEBUG_GRAPH")


def log_state(label: str, data, color: str = "\033[94m"):
    if not DEBUG_GRAPH:
        return
    print(f"{color}\n--- {label} ---\033[0m")
    try:
        print(json.dumps(data, indent=2, default=str))
    except Exception:
        print(data)
    print("\033[90m" + "-" * 60 + "\033[0m")