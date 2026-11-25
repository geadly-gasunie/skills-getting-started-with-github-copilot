from concurrent.futures import ThreadPoolExecutor
import time

import pytest
from fastapi.testclient import TestClient

import src.app as app_module


class SlowMembershipList(list):
    def __contains__(self, value):
        time.sleep(0.02)
        return super().__contains__(value)


@pytest.fixture
def activity_data(monkeypatch):
    activities = {
        "Chess Club": {
            "description": "Play chess",
            "schedule": "Fridays",
            "max_participants": 12,
            "participants": ["existing@example.com"],
        },
        "Art Club": {
            "description": "Make art",
            "schedule": "Wednesdays",
            "max_participants": 10,
            "participants": [],
        },
    }
    monkeypatch.setattr(app_module, "activities", activities)
    return activities


@pytest.fixture
def client(activity_data):
    with TestClient(app_module.app) as test_client:
        yield test_client


def test_root_redirects_to_static_index(client):
    # Arrange: the client fixture supplies an isolated application.

    # Act
    response = client.get("/", follow_redirects=False)
    index_response = client.get("/static/index.html")

    # Assert
    assert response.status_code == 307
    assert response.headers["location"] == "/static/index.html"
    assert index_response.status_code == 200


def test_list_activities(client, activity_data):
    # Arrange: activity_data supplies the expected activities.

    # Act
    response = client.get("/activities")

    # Assert
    assert response.status_code == 200
    assert response.json() == activity_data


def test_signup_updates_activities(client):
    # Arrange
    email = "new+student@example.com"

    # Act
    response = client.post("/activities/Chess%20Club/signup", params={"email": email})
    activities = client.get("/activities").json()

    # Assert
    assert response.status_code == 200
    assert response.json() == {"message": f"Signed up {email} for Chess Club"}
    assert activities["Chess Club"]["participants"] == [
        "existing@example.com",
        email,
    ]


def test_concurrent_signup_only_adds_student_once(client, activity_data):
    email = "new+student@example.com"
    activity_data["Chess Club"]["participants"] = SlowMembershipList(
        activity_data["Chess Club"]["participants"]
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(
            lambda _: client.post(
                "/activities/Chess%20Club/signup", params={"email": email}
            ),
            range(2),
        ))

    assert sorted(response.status_code for response in responses) == [200, 400]
    assert activity_data["Chess Club"]["participants"].count(email) == 1


@pytest.mark.parametrize(
    ("activity", "email", "status", "detail"),
    [
        ("Chess Club", "existing@example.com", 400, "Student is already signed up"),
        ("Unknown Club", "new@example.com", 404, "Activity not found"),
    ],
)
def test_failed_signup_does_not_change_participants(client, activity_data, activity, email, status, detail):
    # Arrange
    before = activity_data["Chess Club"]["participants"].copy()

    # Act
    response = client.post(f"/activities/{activity}/signup", params={"email": email})
    activities = client.get("/activities").json()

    # Assert
    assert response.status_code == status
    assert response.json()["detail"] == detail
    assert activities["Chess Club"]["participants"] == before


def test_unregister_updates_activities(client):
    # Arrange
    email = "existing@example.com"

    # Act
    response = client.delete("/activities/Chess%20Club/participants", params={"email": email})
    activities = client.get("/activities").json()

    # Assert
    assert response.status_code == 200
    assert response.json() == {"message": f"Unregistered {email} from Chess Club"}
    assert activities["Chess Club"]["participants"] == []


def test_concurrent_unregister_returns_not_found_after_first_removal(client, activity_data):
    email = "existing@example.com"
    activity_data["Chess Club"]["participants"] = SlowMembershipList(
        activity_data["Chess Club"]["participants"]
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(
            lambda _: client.delete(
                "/activities/Chess%20Club/participants", params={"email": email}
            ),
            range(2),
        ))

    assert sorted(response.status_code for response in responses) == [200, 404]
    assert email not in activity_data["Chess Club"]["participants"]


@pytest.mark.parametrize(
    ("activity", "email", "detail"),
    [
        ("Chess Club", "missing@example.com", "Participant not found"),
        ("Unknown Club", "existing@example.com", "Activity not found"),
    ],
)
def test_failed_unregister_does_not_change_participants(client, activity_data, activity, email, detail):
    # Arrange
    before = activity_data["Chess Club"]["participants"].copy()

    # Act
    response = client.delete(f"/activities/{activity}/participants", params={"email": email})
    activities = client.get("/activities").json()

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == detail
    assert activities["Chess Club"]["participants"] == before


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/activities/Chess%20Club/signup"),
        ("DELETE", "/activities/Chess%20Club/participants"),
    ],
)
def test_missing_email_is_rejected(client, activity_data, method, path):
    # Arrange
    before = activity_data["Chess Club"]["participants"].copy()

    # Act
    response = client.request(method, path)
    activities = client.get("/activities").json()

    # Assert
    assert response.status_code == 422
    assert activities["Chess Club"]["participants"] == before
