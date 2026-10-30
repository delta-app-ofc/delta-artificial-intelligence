"""Autenticação JWT: o user_id só pode vir de um token válido."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user_id
from tests.isolation.helpers import JWT_SECRET, auth_header, make_token


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(jwt_secret=JWT_SECRET))
    app = FastAPI()

    @app.get("/quem")
    def quem(user_id: int = Depends(get_current_user_id)):
        return {"user_id": user_id}

    return TestClient(app)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_token_valido_devolve_o_id_do_sub(client):
    response = client.get("/quem", headers=auth_header(7))
    assert response.status_code == 200
    assert response.json() == {"user_id": 7}


def test_sem_token_responde_401(client):
    response = client.get("/quem")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_token_expirado_responde_401(client):
    assert client.get("/quem", headers=_bearer(make_token(7, expires_in=-10))).status_code == 401


def test_token_assinado_com_outro_segredo_responde_401(client):
    other = make_token(7, secret="outro-segredo-com-mais-de-32-caracteres!!")
    assert client.get("/quem", headers=_bearer(other)).status_code == 401


def test_token_sem_assinatura_responde_401(client):
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    unsigned = jwt.encode({"sub": "7", "exp": exp}, None, algorithm="none")
    assert client.get("/quem", headers=_bearer(unsigned)).status_code == 401


def test_token_sem_exp_ou_sem_sub_responde_401(client):
    no_exp = jwt.encode({"sub": "7"}, JWT_SECRET, algorithm="HS256")
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    no_sub = jwt.encode({"exp": exp}, JWT_SECRET, algorithm="HS256")
    assert client.get("/quem", headers=_bearer(no_exp)).status_code == 401
    assert client.get("/quem", headers=_bearer(no_sub)).status_code == 401


@pytest.mark.parametrize("sub", ["abc", "0", "-3", "+7", " 7", "7 ", "1_0", "07", "1.5", "", str(2**31)])
def test_sub_que_nao_e_inteiro_positivo_responde_401(client, sub):
    assert client.get("/quem", headers=_bearer(make_token(sub))).status_code == 401


def test_sub_numerico_em_vez_de_texto_responde_401(client):
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode({"sub": 7, "exp": exp}, JWT_SECRET, algorithm="HS256")
    assert client.get("/quem", headers=_bearer(token)).status_code == 401


def test_lixo_no_lugar_do_token_responde_401(client):
    assert client.get("/quem", headers=_bearer("isto-nao-e-um-jwt")).status_code == 401


@pytest.mark.parametrize("secret", [None, "", "curto"])
def test_segredo_ausente_ou_fraco_bloqueia_tudo_com_503(client, monkeypatch, secret):
    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(jwt_secret=secret))
    assert client.get("/quem", headers=auth_header(7)).status_code == 503
    assert client.get("/quem").status_code == 503


def test_user_id_na_query_nao_muda_a_identidade(client):
    response = client.get("/quem?user_id=99", headers=auth_header(7))
    assert response.json() == {"user_id": 7}
