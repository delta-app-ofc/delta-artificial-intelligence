"""Bootstrap de path para os testes.

Garante que a raiz do repositório esteja em sys.path para import app.*
funcionar mesmo com pytest chamado diretamente (sem python -m pytest).
"""

import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))
