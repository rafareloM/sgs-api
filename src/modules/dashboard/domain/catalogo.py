"""Catálogo das consultas e views expostas pela spec 011 (R3.1; design § Rotas).

Lista fixa no código, uma entrada por rota de leitura da 011, inclusive o histórico da unidade, o
log do banco e as partições, que ficam no módulo `audit`. Cada entrada diz a permissão que a rota
exige; quem filtra pelas permissões do usuário é a application (R3.2).
"""

from dataclasses import dataclass

DASHBOARD_READ = "dashboard:read"
AUDITORIA_READ = "auditoria:read"


@dataclass(frozen=True, slots=True)
class Parametro:
    """Parâmetro de consulta aceito pela rota."""

    nome: str
    descricao: str
    obrigatorio: bool = False


@dataclass(frozen=True, slots=True)
class Coluna:
    """Coluna (campo) de cada item da resposta."""

    nome: str
    descricao: str


@dataclass(frozen=True, slots=True)
class ConsultaDescrita:
    """Uma consulta do catálogo (011/R3.1). `exige_escopo_global` marca a rota que só executa com
    a permissão em escopo global (o log do banco e as partições, 011/R7.8)."""

    slug: str
    titulo: str
    justificativa: str
    rota: str
    parametros: tuple[Parametro, ...]
    colunas: tuple[Coluna, ...]
    permissao: str
    grafico_sugerido: str
    exige_escopo_global: bool = False


_DISTRITO = Parametro("distrito", "Id do distrito sanitário.")
_TIPO = Parametro("tipo", "Id do tipo de unidade.")
_PAGINA = Parametro("pagina", "Número da página, a partir de 1 (padrão 1).")
_TAMANHO = Parametro("tamanho", "Itens por página (padrão 20, máximo 100).")
_PERIODO = (
    Parametro("de", "Início do período, incluído (data e hora com fuso)."),
    Parametro("ate", "Fim do período, incluído (data e hora com fuso)."),
)

_RESUMO_DA_UNIDADE = (
    Coluna("id", "Id da unidade."),
    Coluna("nome", "Nome da unidade."),
    Coluna("cnes", "Código CNES; nulo se a unidade não tem."),
    Coluna("tipo", "Nome do tipo de unidade."),
    Coluna("distrito", "Nome do distrito sanitário."),
)

CATALOGO: tuple[ConsultaDescrita, ...] = (
    ConsultaDescrita(
        slug="unidades-sem-servico",
        titulo="Unidades sem serviço cadastrado",
        justificativa=(
            "Unidade sem nenhum serviço é uma lacuna do cadastro: ou o serviço existe e não foi"
            " cadastrado, ou a unidade não oferta nada e pede revisão. Mostra onde agir"
            " (anti join entre unidades e serviços)."
        ),
        rota="/api/v1/dashboard/consultas/unidades-sem-servico",
        parametros=(_DISTRITO, _TIPO, _PAGINA, _TAMANHO),
        colunas=_RESUMO_DA_UNIDADE,
        permissao=DASHBOARD_READ,
        grafico_sugerido="tabela",
    ),
    ConsultaDescrita(
        slug="conciliacao-unidade-equipamento",
        titulo="Conciliação entre unidades e equipamentos",
        justificativa=(
            "Unidade e equipamento são cadastros distintos que se confundem. Ver os pares, as"
            " unidades sem equipamento e os equipamentos sem unidade juntos mostra o que falta"
            " ligar (full outer join)."
        ),
        rota="/api/v1/dashboard/consultas/conciliacao-unidade-equipamento",
        parametros=(_DISTRITO, _TIPO, _PAGINA, _TAMANHO),
        colunas=(
            Coluna("unidade_id", "Id da unidade; nulo no equipamento sem unidade."),
            Coluna("unidade_nome", "Nome da unidade."),
            Coluna("distrito", "Nome do distrito da unidade."),
            Coluna("equipamento_id", "Id do equipamento; nulo na unidade sem equipamento."),
            Coluna("equipamento_nome", "Nome do equipamento."),
            Coluna("equipamento_tipo", "Nome do tipo do equipamento."),
            Coluna(
                "situacao",
                "par, unidade_sem_equipamento ou equipamento_sem_unidade.",
            ),
        ),
        permissao=DASHBOARD_READ,
        grafico_sugerido="barras empilhadas por situação",
    ),
    ConsultaDescrita(
        slug="distritos-cnes-acima-da-media",
        titulo="Distritos com mais unidades sem CNES que a rede",
        justificativa=(
            "Unidade sem CNES está fora do cadastro federal. Comparar o percentual de cada"
            " distrito com o da rede mostra onde a lacuna se concentra (subconsulta escalar)."
        ),
        rota="/api/v1/dashboard/consultas/distritos-cnes-acima-da-media",
        parametros=(_TIPO,),
        colunas=(
            Coluna("percentual_rede", "Percentual de unidades sem CNES na rede (0 a 100)."),
            Coluna("distritos[].id", "Id do distrito."),
            Coluna("distritos[].nome", "Nome do distrito."),
            Coluna("distritos[].total_unidades", "Unidades do distrito."),
            Coluna("distritos[].sem_cnes", "Unidades do distrito sem CNES."),
            Coluna("distritos[].percentual", "Percentual de unidades sem CNES (0 a 100)."),
        ),
        permissao=DASHBOARD_READ,
        grafico_sugerido="barras por distrito com linha de referência da rede",
    ),
    ConsultaDescrita(
        slug="unidades-servico-fora-cnes",
        titulo="Unidades com serviço fora do CNES",
        justificativa=(
            "Serviço ofertado e não registrado no CNES é divergência com o cadastro federal."
            " Lista as unidades que têm ao menos um, com a quantidade (subconsulta EXISTS)."
        ),
        rota="/api/v1/dashboard/consultas/unidades-servico-fora-cnes",
        parametros=(_DISTRITO, _TIPO, _PAGINA, _TAMANHO),
        colunas=(
            *_RESUMO_DA_UNIDADE,
            Coluna("servicos_fora_cnes", "Quantidade de serviços fora do CNES."),
        ),
        permissao=DASHBOARD_READ,
        grafico_sugerido="barras horizontais por unidade",
    ),
    ConsultaDescrita(
        slug="inventario",
        titulo="Inventário da rede",
        justificativa=(
            "Uma linha por unidade, com situação cadastral e as contagens de equipamentos e"
            " serviços, para a visão geral da rede sem dado pessoal (view vw_unit_inventory)."
        ),
        rota="/api/v1/dashboard/consultas/inventario",
        parametros=(_DISTRITO, _TIPO, _PAGINA, _TAMANHO),
        colunas=(
            Coluna("id", "Id da unidade."),
            Coluna("nome", "Nome da unidade."),
            Coluna("cnes", "Código CNES; nulo se a unidade não tem."),
            Coluna("status", "Status da unidade."),
            Coluna("situacao_cadastral", "inativa, com_pendencias, sem_cnes ou regular."),
            Coluna("tipo_id", "Id do tipo de unidade."),
            Coluna("tipo", "Nome do tipo de unidade."),
            Coluna("area_tecnica_id", "Id da área técnica."),
            Coluna("area_tecnica", "Nome da área técnica."),
            Coluna("distrito_id", "Id do distrito sanitário."),
            Coluna("distrito", "Nome do distrito sanitário."),
            Coluna("equipamentos", "Quantidade de equipamentos."),
            Coluna("servicos", "Quantidade de serviços."),
            Coluna("servicos_fora_cnes", "Quantidade de serviços fora do CNES."),
        ),
        permissao=DASHBOARD_READ,
        grafico_sugerido="tabela com barras por situação cadastral",
    ),
    ConsultaDescrita(
        slug="historico-da-unidade",
        titulo="Histórico de alterações da unidade",
        justificativa=(
            "Quem mudou o quê e quando na unidade e nos seus equipamentos e serviços, com o"
            " valor de antes e o de depois, para rastrear o cadastro (view vw_unit_history)."
        ),
        rota="/api/v1/unidades/{id}/historico",
        parametros=(
            Parametro("id", "Id da unidade (no caminho).", obrigatorio=True),
            *_PERIODO,
            Parametro("autor", "Id do usuário autor do evento."),
            Parametro("campo", "Nome do campo alterado."),
            _PAGINA,
            _TAMANHO,
        ),
        colunas=(
            Coluna("id", "Id do evento."),
            Coluna("ocorrido_em", "Data e hora do evento."),
            Coluna("acao", "Ação registrada."),
            Coluna("autor_id", "Id do autor; nulo em tarefa do sistema."),
            Coluna("autor_nome", "Nome do autor."),
            Coluna("autor_papeis", "Papéis do autor no momento do evento."),
            Coluna("mudancas", "Lista de {campo, de, para}."),
            Coluna("metadados", "Dados complementares do evento."),
        ),
        permissao=AUDITORIA_READ,
        grafico_sugerido="linha do tempo",
    ),
    ConsultaDescrita(
        slug="log-do-banco",
        titulo="Log do banco: alterações do cadastro",
        justificativa=(
            "O PostgreSQL registra toda alteração do cadastro, inclusive as feitas fora da API;"
            " o Auditor confere o que mudou sem depender da aplicação (trigger de log)."
        ),
        rota="/api/v1/auditoria/banco",
        parametros=(
            *_PERIODO,
            Parametro("tabela", "health_units, equipments ou services."),
            Parametro("fora_da_api", "Verdadeiro: só alterações feitas fora da API."),
            _PAGINA,
            _TAMANHO,
        ),
        colunas=(
            Coluna("ocorrido_em", "Data e hora da alteração."),
            Coluna("tabela", "Tabela alterada."),
            Coluna("operacao", "INSERT, UPDATE ou DELETE."),
            Coluna("linha_id", "Id da linha alterada."),
            Coluna("colunas_alteradas", "Cada coluna com o valor de antes e o de depois."),
            Coluna("usuario_banco", "Usuário de banco que fez a alteração."),
            Coluna("via_api", "Falso se a alteração foi feita fora da API."),
        ),
        permissao=AUDITORIA_READ,
        grafico_sugerido="tabela",
        exige_escopo_global=True,
    ),
    ConsultaDescrita(
        slug="particoes-do-log",
        titulo="Partições do log do banco",
        justificativa=(
            "O log é particionado por mês; ver cada partição com o intervalo e a quantidade de"
            " registros mostra o volume e o que cai na partição padrão."
        ),
        rota="/api/v1/auditoria/banco/particoes",
        parametros=(),
        colunas=(
            Coluna("nome", "Nome da partição."),
            Coluna("de", "Início do intervalo, incluído; nulo na DEFAULT."),
            Coluna("ate", "Fim do intervalo, excluído; nulo na DEFAULT."),
            Coluna("registros", "Quantidade de registros."),
        ),
        permissao=AUDITORIA_READ,
        grafico_sugerido="barras por partição",
        exige_escopo_global=True,
    ),
)
