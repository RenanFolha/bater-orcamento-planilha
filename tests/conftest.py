import sys
from pathlib import Path

# frete_service.py, frete_db.py etc. vivem na raiz do projeto (não são um
# pacote instalável) — garante que a raiz esteja no sys.path independente
# de rootdir/importmode do pytest.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
