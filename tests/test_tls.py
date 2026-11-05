"""As chamadas HTTPS usam o certifi e continuam verificando certificado e nome do servidor."""
import ssl
import zoneinfo

import conftest  # noqa: F401  (coloca src/ no caminho de importação)
from encosta_rpa.config import contexto_tls


def test_contexto_verifica_certificado_e_nome():
    contexto = contexto_tls()
    assert contexto.verify_mode == ssl.CERT_REQUIRED
    assert contexto.check_hostname is True


def test_fuso_disponivel_sem_base_do_sistema():
    assert zoneinfo.ZoneInfo("America/Sao_Paulo").key == "America/Sao_Paulo"
