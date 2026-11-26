"""Todo `Connection` do `ldap3` em `src/` desliga o referral (004/R1.13, revisão da frente A, B1).

O padrão do `ldap3` é `auto_referrals=True`: diante de um referral, a conexão refaz o bind com a
mesma senha no host indicado, em claro se o referral for `ldap://`. O teste lê o código-fonte, e
assim uma conexão nova não esquece o argumento.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def _modulos_com_ldap3() -> list[tuple[Path, ast.Module]]:
    modulos = []
    for arquivo in sorted(SRC.rglob("*.py")):
        texto = arquivo.read_text(encoding="utf-8")
        if "ldap3" in texto:
            modulos.append((arquivo, ast.parse(texto, filename=str(arquivo))))
    return modulos


def _nome_chamado(chamada: ast.Call) -> str:
    funcao = chamada.func
    if isinstance(funcao, ast.Attribute):
        return funcao.attr
    return funcao.id if isinstance(funcao, ast.Name) else ""


def _desliga_referral(chamada: ast.Call) -> bool:
    return any(
        argumento.arg == "auto_referrals"
        and isinstance(argumento.value, ast.Constant)
        and argumento.value.value is False
        for argumento in chamada.keywords
    )


def test_toda_conexao_ldap3_desliga_auto_referrals() -> None:
    """004/R1.13"""
    conexoes, sem_desligar = 0, []
    for arquivo, modulo in _modulos_com_ldap3():
        for no in ast.walk(modulo):
            if isinstance(no, ast.Call) and _nome_chamado(no) == "Connection":
                conexoes += 1
                if not _desliga_referral(no):
                    sem_desligar.append(f"{arquivo.relative_to(SRC.parent)}:{no.lineno}")

    assert conexoes > 0, "nenhum Connection do ldap3 encontrado: o teste perdeu o alvo"
    assert not sem_desligar, f"Connection sem auto_referrals=False: {sem_desligar}"
