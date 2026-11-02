"""Autenticação compatível com o back-end: token RS256 conferido com a chave pública, e usuário ativo.

Os tokens têm o mesmo formato que o TokenService do delta-api-postgres emite: cabeçalho com `alg=RS256`,
`kid=delta-1` e `typ=JWT`; claims `iss`, `aud` (lista), `sub` (id do usuário em texto), `jti`, `iat` e `exp`.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.config import load_settings
from app.data import db_postgres
from app.tools.exceptions import DatabaseConnectionError, DatabaseQueryError
from tests.conftest import JWT_SECRET, auth_settings


def _par_rsa(bits=2048):
    privada = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    pem_privada = privada.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pem_publica = privada.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return pem_privada, pem_publica


@pytest.fixture(scope="module")
def par():
    return _par_rsa()


@pytest.fixture(scope="module")
def outro_par():
    return _par_rsa()


def token_do_backend(privada, user_id="7", *, expira_em=900, headers=None, **claims):
    """Token no formato do back-end Java; `claims` sobrescreve (ou, com None, remove) campos."""
    agora = int(time.time())
    corpo = {
        "iss": "delta-api", "aud": ["delta-api"], "sub": user_id, "jti": str(uuid.uuid4()),
        "iat": agora, "exp": agora + expira_em, **claims,
    }
    corpo = {k: v for k, v in corpo.items() if v is not None}
    cabecalho = {"kid": "delta-1", "typ": "JWT", **(headers or {})}
    cabecalho = {k: v for k, v in cabecalho.items() if v is not None}
    return jwt.encode(corpo, privada, algorithm="RS256", headers=cabecalho)


def forjar_hs256_com_chave_publica(pem_publica, user_id="7"):
    """O ataque clássico: assina com HS256 usando o TEXTO da chave pública como se fosse o segredo."""
    def b64(dado):
        return base64.urlsafe_b64encode(json.dumps(dado, separators=(",", ":")).encode()).rstrip(b"=")

    corpo = {"iss": "delta-api", "aud": ["delta-api"], "sub": user_id, "exp": int(time.time()) + 900}
    assinar = b64({"alg": "HS256", "typ": "JWT", "kid": "delta-1"}) + b"." + b64(corpo)
    assinatura = hmac.new(pem_publica.encode(), assinar, hashlib.sha256).digest()
    return (assinar + b"." + base64.urlsafe_b64encode(assinatura).rstrip(b"=")).decode()


@pytest.fixture
def app_protegido():
    app = FastAPI()

    @app.get("/quem")
    def quem(user_id: int = Depends(auth.get_current_user_id)):
        return {"user_id": user_id}

    return TestClient(app)


@pytest.fixture
def usa(monkeypatch):
    def configura(**sobrescritas):
        monkeypatch.setattr("app.auth.get_settings", lambda: auth_settings(**sobrescritas))
    return configura


def chama(client, token=None):
    cabecalhos = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.get("/quem", headers=cabecalhos)


# --- token do back-end aceito --------------------------------------------------------------------


def test_token_do_backend_e_aceito_e_devolve_o_id_do_sub(app_protegido, usa, par):
    privada, publica = par
    usa(auth_public_key=publica)

    resposta = chama(app_protegido, token_do_backend(privada, "12345"))

    assert resposta.status_code == 200 and resposta.json() == {"user_id": 12345}


def test_aud_como_texto_tambem_e_aceito(app_protegido, usa, par):
    privada, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, token_do_backend(privada, aud="delta-api")).status_code == 200


def test_pequena_diferenca_de_relogio_e_tolerada(app_protegido, usa, par):
    privada, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, token_do_backend(privada, expira_em=-3)).status_code == 200


# --- token recusado --------------------------------------------------------------------------------


def test_assinado_por_outra_chave_e_recusado(app_protegido, usa, par, outro_par):
    _, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, token_do_backend(outro_par[0])).status_code == 401


@pytest.mark.parametrize("claims", [{"iss": "outro-emissor"}, {"aud": ["outra-api"]}, {"aud": "outra-api"}])
def test_iss_ou_aud_errados_sao_recusados(app_protegido, usa, par, claims):
    privada, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, token_do_backend(privada, **claims)).status_code == 401


@pytest.mark.parametrize("campo", ["iss", "aud", "exp", "sub"])
def test_claim_obrigatorio_ausente_e_recusado(app_protegido, usa, par, campo):
    privada, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, token_do_backend(privada, **{campo: None})).status_code == 401


def test_token_vencido_e_recusado(app_protegido, usa, par):
    privada, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, token_do_backend(privada, expira_em=-60)).status_code == 401


@pytest.mark.parametrize("sub", ["0", "-1", "abc", "007", "1.5", "", "2147483648"])
def test_sub_invalido_e_recusado(app_protegido, usa, par, sub):
    privada, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, token_do_backend(privada, sub)).status_code == 401


def test_sub_numerico_em_vez_de_texto_e_recusado(app_protegido, usa, par):
    privada, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, token_do_backend(privada, sub=7)).status_code == 401


def test_kid_errado_ou_ausente_e_recusado(app_protegido, usa, par):
    privada, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, token_do_backend(privada, headers={"kid": "delta-99"})).status_code == 401
    assert chama(app_protegido, token_do_backend(privada, headers={"kid": None})).status_code == 401


def test_sem_auth_key_id_o_kid_nao_e_conferido(app_protegido, usa, par):
    privada, publica = par
    usa(auth_public_key=publica, auth_key_id="")

    assert chama(app_protegido, token_do_backend(privada, headers={"kid": "qualquer"})).status_code == 200


def test_confusao_de_algoritmo_hs256_com_a_chave_publica_e_recusada(app_protegido, usa, par):
    _, publica = par
    usa(auth_public_key=publica)

    assert chama(app_protegido, forjar_hs256_com_chave_publica(publica)).status_code == 401


def test_algoritmo_none_e_recusado(app_protegido, usa, par):
    _, publica = par

    def b64(dado):
        return base64.urlsafe_b64encode(json.dumps(dado).encode()).rstrip(b"=").decode()

    corpo = {"iss": "delta-api", "aud": ["delta-api"], "sub": "7", "exp": int(time.time()) + 900}
    usa(auth_public_key=publica)

    assert chama(app_protegido, f"{b64({'alg': 'none', 'kid': 'delta-1'})}.{b64(corpo)}.").status_code == 401


def test_sem_token_ou_lixo_sao_recusados_com_www_authenticate(app_protegido, usa, par):
    usa(auth_public_key=par[1])

    for resposta in (chama(app_protegido), chama(app_protegido, "nao-e-um-jwt")):
        assert resposta.status_code == 401
        assert resposta.headers["www-authenticate"] == "Bearer"


# --- uma forma de autenticação por vez ----------------------------------------------------------------


def test_com_chave_publica_o_segredo_hs256_nao_vale(app_protegido, usa, par):
    _, publica = par
    usa(auth_public_key=publica, jwt_secret=JWT_SECRET)
    hs256 = jwt.encode(
        {"sub": "7", "exp": int(time.time()) + 900, "iss": "delta-api", "aud": ["delta-api"]},
        JWT_SECRET, algorithm="HS256", headers={"kid": "delta-1"},
    )

    assert chama(app_protegido, hs256).status_code == 401


def test_so_com_segredo_em_desenvolvimento_vale_hs256(app_protegido, usa):
    usa(jwt_secret=JWT_SECRET, app_env="development")
    token = jwt.encode({"sub": "7", "exp": int(time.time()) + 900}, JWT_SECRET, algorithm="HS256")

    assert chama(app_protegido, token).json() == {"user_id": 7}


def test_so_com_segredo_o_token_rs256_e_recusado(app_protegido, usa, par):
    usa(jwt_secret=JWT_SECRET)

    assert chama(app_protegido, token_do_backend(par[0])).status_code == 401


@pytest.mark.parametrize("ambiente", ["staging", "production"])
def test_hs256_e_recusado_fora_de_desenvolvimento_e_teste(app_protegido, usa, ambiente):
    usa(jwt_secret=JWT_SECRET, app_env=ambiente)
    token = jwt.encode({"sub": "7", "exp": int(time.time()) + 900}, JWT_SECRET, algorithm="HS256")

    assert chama(app_protegido, token).status_code == 503


@pytest.mark.parametrize("ambiente", ["staging", "production"])
def test_rs256_funciona_em_producao(app_protegido, usa, par, ambiente):
    usa(auth_public_key=par[1], app_env=ambiente)

    assert chama(app_protegido, token_do_backend(par[0])).status_code == 200


def test_sem_nenhuma_configuracao_bloqueia_tudo_com_503(app_protegido, usa, par):
    usa()

    assert chama(app_protegido).status_code == 503
    assert chama(app_protegido, token_do_backend(par[0])).status_code == 503


def test_segredo_fraco_bloqueia_com_503(app_protegido, usa):
    usa(jwt_secret="curto")

    assert chama(app_protegido).status_code == 503


@pytest.mark.parametrize("campo", ["auth_issuer", "auth_audience"])
def test_rs256_sem_issuer_ou_audience_configurados_da_503(app_protegido, usa, par, campo):
    usa(auth_public_key=par[1], **{campo: ""})

    assert chama(app_protegido, token_do_backend(par[0])).status_code == 503


# --- de onde vem a chave pública -------------------------------------------------------------------------


@pytest.fixture
def arquivo_da_chave(tmp_path, par):
    caminho = tmp_path / "public.pem"
    caminho.write_text(par[1], encoding="utf-8")
    return caminho


def test_chave_por_caminho_de_arquivo(app_protegido, usa, par, arquivo_da_chave):
    usa(auth_public_key=str(arquivo_da_chave))

    assert chama(app_protegido, token_do_backend(par[0])).status_code == 200


@pytest.mark.parametrize("formato", ["file:{p}", "file://{p}", "file:///{p}"])
def test_chave_com_prefixo_file_como_no_backend(app_protegido, usa, par, arquivo_da_chave, formato):
    caminho = arquivo_da_chave.as_posix()
    valor = formato.format(p=caminho.lstrip("/"))
    if not caminho[1:2] == ":":  # Linux/macOS: o caminho absoluto já começa com /
        valor = formato.format(p=caminho)
        valor = valor.replace("file:////", "file:///")
    usa(auth_public_key=valor)

    assert chama(app_protegido, token_do_backend(par[0])).status_code == 200


def test_arquivo_inexistente_da_503_sem_vazar_o_caminho(app_protegido, usa, par, tmp_path, caplog):
    segredo = str(tmp_path / "chave-secreta-xyz.pem")
    usa(auth_public_key=segredo)

    resposta = chama(app_protegido, token_do_backend(par[0]))

    assert resposta.status_code == 503
    assert "chave-secreta-xyz" not in resposta.text
    assert "chave-secreta-xyz" not in caplog.text


@pytest.mark.parametrize("conteudo", ["-----BEGIN PUBLIC KEY-----\nlixo\n-----END PUBLIC KEY-----", "isto nao e uma chave"])
def test_chave_invalida_da_503(app_protegido, usa, par, tmp_path, conteudo):
    arquivo = tmp_path / "ruim.pem"
    arquivo.write_text(conteudo, encoding="utf-8")
    usa(auth_public_key=str(arquivo))

    assert chama(app_protegido, token_do_backend(par[0])).status_code == 503


def test_chave_rsa_pequena_ou_de_outro_tipo_da_503(app_protegido, usa, par):
    pequena = _par_rsa(1024)[1]
    curva = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()

    for chave in (pequena, curva):
        usa(auth_public_key=chave)
        assert chama(app_protegido, token_do_backend(par[0])).status_code == 503


# --- usuário ativo -----------------------------------------------------------------------------------------


@pytest.fixture
def banco(monkeypatch):
    chamadas = []
    estado = {"resultado": True}

    def falso(user_id):
        chamadas.append(user_id)
        if isinstance(estado["resultado"], Exception):
            raise estado["resultado"]
        return estado["resultado"]

    monkeypatch.setattr(db_postgres, "is_user_active", falso)
    return type("Banco", (), {"chamadas": chamadas, "estado": estado})


def test_usuario_ativo_passa(app_protegido, usa, par, banco):
    usa(auth_public_key=par[1], auth_check_active=True)

    assert chama(app_protegido, token_do_backend(par[0], "42")).status_code == 200
    assert banco.chamadas == [42]


def test_usuario_inativo_ou_inexistente_e_recusado_com_o_mesmo_401(app_protegido, usa, par, banco):
    usa(auth_public_key=par[1], auth_check_active=True)
    banco.estado["resultado"] = False

    resposta = chama(app_protegido, token_do_backend(par[0]))

    assert resposta.status_code == 401 and resposta.json() == {"detail": "Token ausente ou inválido."}


def test_banco_fora_bloqueia_com_503_e_sem_detalhes(app_protegido, usa, par, banco):
    usa(auth_public_key=par[1], auth_check_active=True)
    banco.estado["resultado"] = DatabaseConnectionError("PostgreSQL")

    resposta = chama(app_protegido, token_do_backend(par[0]))

    assert resposta.status_code == 503 and "PostgreSQL" not in resposta.text


def test_conferencia_desligada_nao_consulta_o_banco(app_protegido, usa, par, banco):
    usa(auth_public_key=par[1], auth_check_active=False)

    assert chama(app_protegido, token_do_backend(par[0])).status_code == 200
    assert banco.chamadas == []


def test_token_invalido_nao_chega_a_consultar_o_banco(app_protegido, usa, par, outro_par, banco):
    usa(auth_public_key=par[1], auth_check_active=True)

    chama(app_protegido, token_do_backend(outro_par[0]))
    chama(app_protegido, token_do_backend(par[0], expira_em=-600))
    chama(app_protegido, "lixo")
    chama(app_protegido)

    assert banco.chamadas == []


def test_funciona_tambem_no_modo_hs256_de_desenvolvimento(app_protegido, usa, banco):
    usa(jwt_secret=JWT_SECRET, auth_check_active=True)
    banco.estado["resultado"] = False
    token = jwt.encode({"sub": "7", "exp": int(time.time()) + 900}, JWT_SECRET, algorithm="HS256")

    assert chama(app_protegido, token).status_code == 401


# --- db_postgres.is_user_active ---------------------------------------------------------------------------------


class CursorFalso:
    def __init__(self, linha=None, erro=None):
        self.linha, self.erro, self.consultas = linha, erro, []

    def execute(self, sql, params=None):
        self.consultas.append((sql, params))
        if self.erro:
            raise self.erro

    def fetchone(self):
        return self.linha


def usa_cursor(monkeypatch, cursor):
    from contextlib import contextmanager

    @contextmanager
    def falso():
        yield cursor

    monkeypatch.setattr(db_postgres, "_cursor", falso)


@pytest.mark.parametrize("linha, esperado", [((True,), True), ((False,), False), ((None,), False), (None, False)])
def test_is_user_active_le_o_resultado_da_funcao(monkeypatch, linha, esperado):
    cursor = CursorFalso(linha)
    usa_cursor(monkeypatch, cursor)

    assert db_postgres.is_user_active(9) is esperado
    assert cursor.consultas == [("SELECT fn_user_is_active(%s);", (9,))]


def test_is_user_active_usuario_inexistente_e_inativo(monkeypatch):
    usa_cursor(monkeypatch, CursorFalso(erro=DatabaseQueryError("PostgreSQL", code="P0001")))

    assert db_postgres.is_user_active(9) is False


def test_is_user_active_outros_erros_do_banco_sobem(monkeypatch):
    usa_cursor(monkeypatch, CursorFalso(erro=DatabaseQueryError("PostgreSQL", code="57014")))

    with pytest.raises(DatabaseQueryError):
        db_postgres.is_user_active(9)


# --- configuração ---------------------------------------------------------------------------------------------------


def test_configuracao_padrao_acompanha_o_backend():
    config = load_settings({"APP_ENV": "test"}, env_file=None)

    assert config.auth_public_key is None
    assert (config.auth_issuer, config.auth_audience, config.auth_key_id) == ("delta-api", "delta-api", "delta-1")
    assert config.auth_check_active is True


def test_configuracao_le_as_variaveis_de_ambiente():
    config = load_settings(
        {"APP_ENV": "test", "AUTH_PUBLIC_KEY": "file:/chaves/public.pem", "AUTH_ISSUER": "meu-emissor",
         "AUTH_AUDIENCE": "minha-api", "AUTH_KEY_ID": "delta-2", "AUTH_CHECK_ACTIVE": "false"},
        env_file=None,
    )

    assert config.auth_public_key == "file:/chaves/public.pem"
    assert (config.auth_issuer, config.auth_audience, config.auth_key_id) == ("meu-emissor", "minha-api", "delta-2")
    assert config.auth_check_active is False


def test_valor_invalido_de_auth_check_active_vira_erro_de_configuracao():
    config = load_settings({"APP_ENV": "test", "AUTH_CHECK_ACTIVE": "talvez"}, env_file=None)

    assert ("AUTH_CHECK_ACTIVE", "use true ou false") in config._parse_errors
