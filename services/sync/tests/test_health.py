from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_demo_page_and_tone_are_available(client: TestClient) -> None:
    page = client.get("/demo")
    tone = client.get("/demo/test-tone.wav")

    assert page.status_code == 200
    assert "Connect &amp; arm audio" in page.text
    assert tone.status_code == 200
    assert tone.headers["content-type"] == "audio/wav"
    assert tone.content.startswith(b"RIFF")
