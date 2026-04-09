import signal, threading, logging, requests, json, uuid
from kafka import KafkaConsumer


# Configure the root logger to display INFO level and above messages,
# with each log showing the timestamp, log level, and the message.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Google ADK api_server URL (adjust if your server is running elsewhere)
API_URL = "http://127.0.0.1:8000/run"


def call_adk_agent(agent_name: str, message_text: str, user_id: str = None, session_id: str = None):
    """
    Call a Google ADK agent running in api_server mode.
    
    Args:
        agent_name (str): Name of your agent (app_name).
        message_text (str): Text message to send to the agent.
        user_id (str, optional): Identifier for the user. Defaults to a random UUID.
        session_id (str, optional): Identifier for the session. Defaults to a random UUID.
        
    Returns:
        dict: JSON response from the agent.
    """
    # Generate IDs if not provided
    if not user_id:
        user_id = f"user_{str(uuid.uuid4())[:8]}"
    if not session_id:
        session_id = f"session_{str(uuid.uuid4())[:8]}"
    
    payload = {
        "app_name": agent_name,
        "user_id": "user_1",
        "session_id": "session_1",
        "new_message": {
            "role": "user",
            "parts": [{"text": message_text}]
        }
    }
    
    response = requests.post(API_URL, json=payload)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error {response.status_code}: {response.text}")
    
def extract_agent_text(agent_response):
    """
    Safely extract the text from an ADK agent response.
    
    Args:
        agent_response (list): JSON response from ADK api_server.
        
    Returns:
        str: Cleaned text from the first event's content, stripped of quotes.
    """
    if not agent_response:
        return ""
    
    event = agent_response[0]
    parts = event.get("content", {}).get("parts", [])
    
    text = "".join(part.get("text", "") for part in parts)
    return text.strip('\'"')  # remove surrounding quotes


shutdown_event = threading.Event()  # thread-safe flag to stop listener

def run_listener(topic="events-topic", bootstrap_servers=None, group_id="events-consumers-v1"):
    if bootstrap_servers is None:
        bootstrap_servers = ["localhost:9092"]

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        auto_offset_reset="earliest",
        group_id=group_id,
        enable_auto_commit=True,
        value_deserializer=lambda m: m.decode("utf-8")
    )

    logging.info(f"Listening to Kafka topic '{topic}' on {bootstrap_servers}")

    try:
        while not shutdown_event.is_set():
            records = consumer.poll(timeout_ms=1000)  # 1 second poll
            for tp, messages in records.items():
                for message in messages:
                    logging.info(f"Partition: {message.partition}, Offset: {message.offset}")
                    logging.info(f"Exception trace: {message.value}")

                    # Call the classifier agent
                    result = call_adk_agent("event_classifier_agent", message.value)
                    event_type = extract_agent_text(result)

                    # Decide next action
                    if event_type == "application":
                        result = call_adk_agent("java_event_handler_agent", message.value)
                        print(json.dumps(result, indent=2))
                    else:
                        print(f"Event type: {event_type} (not handled)")


    except Exception as e:
        logging.error(f"Error in Kafka consumer: {e}")
    finally:
        logging.info("Closing Kafka consumer...")
        consumer.close()
        logging.info("Consumer closed gracefully")

# Signal handler
def handle_signal(sig, frame):
    logging.info(f"Received signal {sig}, shutting down...")
    shutdown_event.set()

signal.signal(signal.SIGINT, handle_signal)   # Ctrl+C
signal.signal(signal.SIGTERM, handle_signal)  # docker stop / kill

if __name__ == "__main__":
    run_listener()

