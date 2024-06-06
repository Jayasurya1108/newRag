import os
import pymongo
import streamlit as st
from dotenv import load_dotenv
from datetime import datetime
import google.generativeai as gen_ai
import atexit
import hashlib

# Load environment variables from .env file
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

# Get environment variables
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI")

if GOOGLE_API_KEY is None:
    st.error("Google API key not found. Please make sure it's set in your .env file.")
    st.stop()

if MONGODB_URI is None:
    st.error("MongoDB URI not found. Please make sure it's set in your .env file.")
    st.stop()

# Configure Streamlit page settings
st.set_page_config(
    page_title="Chat with my AI!",
    page_icon=":alien:",
    layout="wide",
)

# Set up MongoDB connection
try:
    client = pymongo.MongoClient(MONGODB_URI)
    db = client["chatbot_db"]
    collection = db["chat_history"]
    user_collection = db["users"]  # Collection for user credentials

    # Ensure text index on 'text' field for full-text search
    collection.create_index([("text", pymongo.TEXT)])
except pymongo.errors.ConfigurationError as e:
    st.error(f"Configuration error: {e}")
    st.stop()
except pymongo.errors.ServerSelectionTimeoutError as e:
    st.error(f"Server selection timeout error: {e}")
    st.stop()
except Exception as e:
    st.error(f"An unexpected error occurred: {e}")
    st.stop()


# Ensure MongoDB client is closed when Streamlit app stops
def close_mongo_client():
    client.close()


atexit.register(close_mongo_client)

# Set up Google Gemini-Pro AI model
gen_ai.configure(api_key=GOOGLE_API_KEY)
model = gen_ai.GenerativeModel('gemini-pro')

# Function to hash passwords
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Function to register a new user
def register_user(username, password):
    hashed_password = hash_password(password)
    user_data = {"username": username, "password": hashed_password}
    user_collection.insert_one(user_data)

# Function to authenticate user
def authenticate_user(username, password):
    hashed_password = hash_password(password)
    user = user_collection.find_one({"username": username, "password": hashed_password})
    return user is not None

# User authentication interface
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None

if not st.session_state.logged_in:
    st.sidebar.title("User Login")

    register = st.sidebar.checkbox("Register")
    if register:
        username = st.sidebar.text_input("Username", key="register_username")
        password = st.sidebar.text_input("Password", type="password", key="register_password")
        if st.sidebar.button("Register"):
            if user_collection.find_one({"username": username}):
                st.sidebar.error("Username already exists")
            else:
                register_user(username, password)
                st.sidebar.success("Registration successful. Please log in.")
    else:
        username = st.sidebar.text_input("Username", key="login_username")
        password = st.sidebar.text_input("Password", type="password", key="login_password")
        if st.sidebar.button("Login"):
            if authenticate_user(username, password):
                st.session_state.logged_in = True
                st.session_state.username = username
                st.sidebar.success("Login successful.")
            else:
                st.sidebar.error("Invalid username or password")
else:
    st.sidebar.write(f"Logged in as {st.session_state.username}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.experimental_rerun()

# Initialize chat session in Streamlit if not already present
if "chat_session" not in st.session_state:
    st.session_state.chat_session = model.start_chat(history=[])
if "messages" not in st.session_state:
    st.session_state.messages = []


# Function to translate roles between Gemini-Pro and Streamlit terminology
def translate_role_for_streamlit(user_role):
    return "assistant" if user_role == "model" else user_role


# Function to store user prompts in MongoDB
def store_message(role, text):
    data = {
        "role": role,
        "text": text,
        "timestamp": datetime.now(),
        "username": st.session_state.username
    }
    collection.insert_one(data)


# Function to retrieve relevant past messages for the logged-in user
def retrieve_relevant_messages(query):
    results = collection.find({"username": st.session_state.username, "$text": {"$search": query}}).sort("timestamp", -1).limit(5)
    return [doc['text'] for doc in results]


# Function to display messages
def display_messages():
    for msg in st.session_state.messages:
        if msg['role'] == 'user':
            st.markdown(f"""
                <div style='text-align: right; background-color: #D9EAD3; padding: 10px; border-radius: 10px; margin: 5px 0; color: black;'>
                    <strong>You:</strong> {msg['text']}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
                <div style='text-align: left; background-color: #F3F3F3; padding: 10px; border-radius: 10px; margin: 5px 0; color: black;'>
                    <strong>Assistant:</strong> {msg['text']}
                </div>
                """, unsafe_allow_html=True)
        if msg.get('retrieved'):
            st.markdown(f"""
                <div style='text-align: left; background-color: #FFE6CC; padding: 10px; border-radius: 10px; margin: 5px 0; color: black;'>
                    <strong>Retrieved Context:</strong> {msg['retrieved']}
                </div>
                """, unsafe_allow_html=True)

if st.session_state.logged_in:
    # Display chat history in sidebar
    st.sidebar.title("Chat History")
    if collection.count_documents({"username": st.session_state.username}) > 0:
        chat_history = collection.find({"username": st.session_state.username}).sort("timestamp")
        for message in chat_history:
            with st.sidebar.expander(f"{message['timestamp']} - {translate_role_for_streamlit(message['role'])}"):
                st.markdown(message['text'])

    # Display the chatbot's title on the page
    st.title("🤖 Zephyr - ChatBot")

    # Display all messages
    display_messages()

    # Input field for user's message
    user_prompt = st.text_input("Ask Zephyr", key=f"user_input_{len(st.session_state.messages)}")
    if user_prompt:
        # Store user's prompt in MongoDB
        store_message("user", user_prompt)

        # Add user's message to session state
        st.session_state.messages.append({"role": "user", "text": user_prompt})

        # Retrieve relevant messages from history
        relevant_messages = retrieve_relevant_messages(user_prompt)
        context = " ".join(relevant_messages)
        combined_prompt = f"{context} {user_prompt}"

        # Add retrieved context to session state for debugging
        st.session_state.messages.append({"role": "system", "text": combined_prompt, "retrieved": relevant_messages})

        # Send combined prompt to Gemini-Pro and get the response
        try:
            gemini_response = st.session_state.chat_session.send_message(combined_prompt)
            response_text = gemini_response.text
        except Exception as e:
            response_text = f"Error: {e}"

        # Store Gemini-Pro's response in MongoDB
        store_message("assistant", response_text)

        # Add Gemini-Pro's response to session state
        st.session_state.messages.append({"role": "assistant", "text": response_text})

        # Refresh the app to display new input box
        st.experimental_rerun()
else:
    st.warning("Please log in to use the chat.")
