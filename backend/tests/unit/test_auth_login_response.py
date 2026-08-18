import pytest
from app.transport.http.schemas import LoginResponse, UserInfo


def test_login_response_has_user_field():
    resp = LoginResponse(access_token="abc.def.ghi", user=UserInfo(id="u-1", username="alice", role="user"))
    dumped = resp.model_dump()
    assert dumped["user"]["username"] == "alice"
    assert dumped["user"]["id"] == "u-1"
    assert dumped["user"]["role"] == "user"
