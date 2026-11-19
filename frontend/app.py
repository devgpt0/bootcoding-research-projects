import streamlit as st
import requests

st.set_page_config(
    page_title="Bootcoding Recruitment",
    page_icon="💼",
    layout="wide"
)

API_URL = "http://127.0.0.1:8000/candidates"
SEND_WHATSAPP_URL = "http://127.0.0.1:8000/send-whatsapp"

# Session state
if "show_whatsapp" not in st.session_state:
    st.session_state.show_whatsapp = False

if "selected_candidate" not in st.session_state:
    st.session_state.selected_candidate = None

if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = {}

if "message_sids" not in st.session_state:
    st.session_state.message_sids = {}

# Fetch candidates
try:
    response = requests.get(API_URL, timeout=5)
    response.raise_for_status()
    candidates = response.json()

except requests.RequestException:
    candidates = []
    st.error("Unable to connect to backend.")

# -------------------------------
# Company Recruitment Homepage
# -------------------------------

col1, col2 = st.columns([6, 1])

with col1:
    st.title("Welcome to Bootcoding")
    st.caption("Build your career with us.")

with col2:
    st.write("")
    st.image(
        "https://cdn.simpleicons.org/whatsapp/25D366",
        width=45
    )

    if st.button("Open WhatsApp", use_container_width=True):
        st.session_state.show_whatsapp = (
            not st.session_state.show_whatsapp
        )
        st.rerun()
st.divider()

st.header("Explore Career Opportunities")

st.write(
    "Discover exciting opportunities and become "
    "a part of the Bootcoding team."
)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Software Developer")
    st.write("Build and maintain software applications.")
    st.button("View Details", key="software_details")

with col2:
    st.subheader("Python Developer")
    st.write("Work on Python and backend development.")
    st.button("View Details", key="python_details")

st.divider()

st.header("Why Join Bootcoding?")
st.write(
    "Learn new technologies, develop your skills "
    "and grow with our team."
)

# -------------------------------
# WhatsApp Web Style Interface
# -------------------------------

if st.session_state.show_whatsapp:

    st.divider()

    header_col1, header_col2 = st.columns([6, 1])

    with header_col1:
        st.image(
          "https://cdn.simpleicons.org/whatsapp/25D366",
           width=35
            )
        st.subheader("WhatsApp")

    with header_col2:
        if st.button("✖ Close"):
            st.session_state.show_whatsapp = False
            st.rerun()

    left, right = st.columns([1, 2])

    # LEFT SIDE: Contacts
    with left:

        st.subheader("Chats")

        search = st.text_input(
            "Search students",
            placeholder="Search by name..."
        )

        filtered_candidates = [
            candidate for candidate in candidates
            if search.lower() in candidate["name"].lower()
        ]

        st.caption(f"Contacts: {len(filtered_candidates)}")

        for candidate in filtered_candidates:

            label = (
                f"👤 {candidate['name']}\n"
                f"{candidate['phone_number']}"
            )

            if st.button(
                label,
                key=f"contact_{candidate['id']}",
                use_container_width=True
            ):
                st.session_state.selected_candidate = candidate["id"]
                st.rerun()

    # RIGHT SIDE: Chat window
    with right:

        selected = next(
            (
                candidate for candidate in candidates
                if candidate["id"] == st.session_state.selected_candidate
            ),
            None
        )

        if selected:

            st.subheader(f"👤 {selected['name']}")
            st.caption(selected["phone_number"])

            st.divider()

            chat_id = str(selected["id"])

            if chat_id not in st.session_state.chat_messages:
                st.session_state.chat_messages[chat_id] = []

            # Display local message previews
            for msg in st.session_state.chat_messages[chat_id]:
                with st.chat_message("user"):
                    st.write(msg)

            message = st.text_area(
                "Message",
                placeholder="Type a message...",
                key=f"message_{chat_id}"
            )

            if st.button(
                "➤ Send",
                key=f"send_{chat_id}"
            ):

                if message.strip():
                    try:
                        send_response = requests.post(
                            SEND_WHATSAPP_URL,
                            json={
                                "to": selected["phone_number"],
                                "message": message.strip(),
                            },
                            timeout=15,
                        )
                        try:
                            response_body = send_response.json()
                        except ValueError:
                            response_body = send_response.text

                        if not send_response.ok:
                            st.error(
                                f"Backend returned HTTP "
                                f"{send_response.status_code}."
                            )
                            if isinstance(response_body, (dict, list)):
                                st.json(response_body)
                            elif response_body:
                                st.code(response_body)
                        else:
                            st.success("Message accepted by the backend.")
                            if isinstance(response_body, (dict, list)):
                                st.json(response_body)
                            elif response_body:
                                st.write(response_body)
                            st.session_state.chat_messages[chat_id].append(
                                message.strip()
                            )
                            message_sid = response_body.get("message_sid")
                            if message_sid:
                                st.session_state.message_sids[chat_id] = message_sid
                            with st.chat_message("user"):
                                st.write(message.strip())
                    except requests.RequestException as e:
                        st.error(
                            f"Could not reach the backend at "
                            f"{SEND_WHATSAPP_URL}: {e}"
                        )
                else:
                    st.warning("Please type a message.")

            message_sid = st.session_state.message_sids.get(chat_id)
            if message_sid and st.button(
                "Check delivery status",
                key=f"check_status_{chat_id}"
            ):
                status_url = (
                    f"http://127.0.0.1:8000/messages/{message_sid}/status"
                )
                try:
                    status_response = requests.get(status_url, timeout=15)
                    try:
                        status_body = status_response.json()
                    except ValueError:
                        status_body = status_response.text

                    if status_response.ok:
                        st.write("Latest Twilio delivery status:")
                        if isinstance(status_body, dict):
                            st.write(
                                "Status:",
                                status_body.get("status", "unknown")
                            )
                            st.write(
                                "Error code:",
                                status_body.get("error_code")
                            )
                            st.write(
                                "Error message:",
                                status_body.get("error_message")
                            )
                            st.json(status_body)
                        elif isinstance(status_body, list):
                            st.json(status_body)
                        elif status_body:
                            st.code(status_body)
                    else:
                        st.error(
                            f"Status lookup returned HTTP "
                            f"{status_response.status_code}."
                        )
                        if isinstance(status_body, (dict, list)):
                            st.json(status_body)
                        elif status_body:
                            st.code(status_body)
                except requests.RequestException as e:
                    st.error(f"Could not retrieve Twilio message status: {e}")

        else:
            st.info(
                "Select a student from the contacts list "
                "to open the conversation."
            )
