from fastapi.testclient import TestClient

from api.main import app


def test_setup_and_interview_pages_are_separate() -> None:
    client = TestClient(app)

    setup = client.get("/")
    interview = client.get("/interview")

    assert setup.status_code == 200
    assert 'id="setup-form"' in setup.text
    assert "Submit configuration" in setup.text
    assert 'id="interview-screen"' not in setup.text
    assert interview.status_code == 200
    assert 'id="begin-interview-button"' in interview.text
    assert 'id="interview-screen"' in interview.text


def test_interview_page_loads_its_separate_script() -> None:
    response = TestClient(app).get("/static/interview.js")

    assert response.status_code == 200
    assert "geminiInterviewConfig" in response.text
    assert "/ws/interview" in response.text
