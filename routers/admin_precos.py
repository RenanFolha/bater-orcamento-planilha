# Desenvolvedor Chefe: RenanFolha

"""CRUD administrativo da tela "Tabela de Preços" (filiais, veículos, taxas,
coleta com preço fixo, categorias, transportes, SLAs, transportadoras
terceirizadas) e o /admin/reload. Todas as rotas exigem login de admin."""

from fastapi import APIRouter, Depends, HTTPException

import frete_db as db
import frete_service as fs
from deps import admin_atualizar, admin_criar, admin_excluir, exigir_admin
from schemas import (
    AliquotaIcmsIn,
    CategoriaIn,
    ColetaCidadeFixaIn,
    DistanciaFixaIn,
    FaixaColetaIn,
    FaixaKmVeiculoIn,
    FilialIn,
    ImportarPracasPedagioRequest,
    PedagioRotaIn,
    PracaPedagioIn,
    PrioridadeRotaIn,
    SlaIn,
    TaxaAdicionalIn,
    TaxaBalsaIn,
    TaxaRegionalIn,
    TransportadoraTerceirizadaIn,
    TransporteIn,
    VeiculoIn,
)

router = APIRouter(prefix="/admin", tags=["Admin - Tabela de Preços"])


@router.post("/reload")
def reload_parametros(usuario: dict = Depends(exigir_admin)):
    """Recarrega os parâmetros direto do banco SQLite.
    Use depois de editar o frete.db (ex: com o DB Browser for SQLite),
    sem precisar reiniciar a API."""
    try:
        fs.carregar_parametros()
        return {"status": "ok", "mensagem": "Parâmetros recarregados a partir do banco."}
    except fs.FreteConfigError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/filiais")
def admin_listar_filiais(usuario: dict = Depends(exigir_admin)):
    return db.listar_filiais_admin()


@router.post("/filiais")
def admin_criar_filial(payload: FilialIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(db.inserir_filial, payload, f"Já existe uma filial chamada '{payload.nome}'.")


@router.put("/filiais/{id_}")
def admin_atualizar_filial(id_: int, payload: FilialIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_filial, id_, payload, f"Já existe uma filial chamada '{payload.nome}'.")


@router.delete("/filiais/{id_}")
def admin_excluir_filial(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(
        db.excluir_filial, id_, db.contar_filiais,
        "Não é possível excluir a última filial cadastrada — o sistema precisa de pelo menos uma.",
    )


@router.get("/veiculos")
def admin_listar_veiculos(usuario: dict = Depends(exigir_admin)):
    return db.listar_veiculos_admin()


@router.post("/veiculos")
def admin_criar_veiculo(payload: VeiculoIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(db.inserir_veiculo, payload, f"Já existe um veículo chamado '{payload.nome}'.")


@router.put("/veiculos/{id_}")
def admin_atualizar_veiculo(id_: int, payload: VeiculoIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_veiculo, id_, payload, f"Já existe um veículo chamado '{payload.nome}'.")


@router.delete("/veiculos/{id_}")
def admin_excluir_veiculo(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(
        db.excluir_veiculo, id_, db.contar_veiculos,
        "Não é possível excluir o último veículo cadastrado — o sistema precisa de pelo menos um.",
    )


@router.get("/faixas-km-veiculo")
def admin_listar_faixas_km_veiculo(usuario: dict = Depends(exigir_admin)):
    return db.listar_faixas_km_veiculo_admin()


@router.post("/faixas-km-veiculo")
def admin_criar_faixa_km_veiculo(payload: FaixaKmVeiculoIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(db.inserir_faixa_km_veiculo, payload, "")


@router.put("/faixas-km-veiculo/{id_}")
def admin_atualizar_faixa_km_veiculo(id_: int, payload: FaixaKmVeiculoIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_faixa_km_veiculo, id_, payload, "")


@router.delete("/faixas-km-veiculo/{id_}")
def admin_excluir_faixa_km_veiculo(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_faixa_km_veiculo, id_)


@router.get("/taxas-adicionais")
def admin_listar_taxas_adicionais(usuario: dict = Depends(exigir_admin)):
    return db.listar_taxas_adicionais_admin()


@router.post("/taxas-adicionais")
def admin_criar_taxa_adicional(payload: TaxaAdicionalIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(db.inserir_taxa_adicional, payload, f"Já existe uma taxa chamada '{payload.nome}'.")


@router.put("/taxas-adicionais/{id_}")
def admin_atualizar_taxa_adicional(id_: int, payload: TaxaAdicionalIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_taxa_adicional, id_, payload, f"Já existe uma taxa chamada '{payload.nome}'.")


@router.delete("/taxas-adicionais/{id_}")
def admin_excluir_taxa_adicional(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_taxa_adicional, id_)


@router.get("/coleta-cidades-fixas")
def admin_listar_coleta_cidades_fixas(usuario: dict = Depends(exigir_admin)):
    return db.listar_coleta_cidades_fixas_admin()


@router.post("/coleta-cidades-fixas")
def admin_criar_coleta_cidade_fixa(payload: ColetaCidadeFixaIn, usuario: dict = Depends(exigir_admin)):
    # msg_conflito=str: a validação de conflito (cidade repetida entre
    # linhas do mesmo filial+veículo) já monta uma mensagem específica em
    # frete_db.py — usar str(exc) em vez de um texto fixo preserva ela.
    return admin_criar(db.inserir_coleta_cidade_fixa, payload, str)


@router.put("/coleta-cidades-fixas/{id_}")
def admin_atualizar_coleta_cidade_fixa(id_: int, payload: ColetaCidadeFixaIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_coleta_cidade_fixa, id_, payload, str)


@router.delete("/coleta-cidades-fixas/{id_}")
def admin_excluir_coleta_cidade_fixa(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_coleta_cidade_fixa, id_)


@router.get("/taxas-regionais")
def admin_listar_taxas_regionais(usuario: dict = Depends(exigir_admin)):
    return db.listar_taxas_regionais_admin()


@router.post("/taxas-regionais")
def admin_criar_taxa_regional(payload: TaxaRegionalIn, usuario: dict = Depends(exigir_admin)):
    # msg_conflito=str: mesmo padrão de coleta-cidades-fixas acima -- a
    # mensagem específica (cidade repetida entre linhas da mesma taxa) já
    # vem montada em frete_db.py.
    return admin_criar(db.inserir_taxa_regional, payload, str)


@router.put("/taxas-regionais/{id_}")
def admin_atualizar_taxa_regional(id_: int, payload: TaxaRegionalIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_taxa_regional, id_, payload, str)


@router.delete("/taxas-regionais/{id_}")
def admin_excluir_taxa_regional(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_taxa_regional, id_)


@router.get("/taxas-balsa")
def admin_listar_taxas_balsa(usuario: dict = Depends(exigir_admin)):
    return db.listar_taxas_balsa_admin()


@router.post("/taxas-balsa")
def admin_criar_taxa_balsa(payload: TaxaBalsaIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(
        db.inserir_taxa_balsa, payload,
        f"Já existe uma taxa de balsa de '{payload.cidade_origem}' → '{payload.cidade_destino}' "
        f"pro veículo '{payload.veiculo}'.",
    )


@router.put("/taxas-balsa/{id_}")
def admin_atualizar_taxa_balsa(id_: int, payload: TaxaBalsaIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(
        db.atualizar_taxa_balsa, id_, payload,
        f"Já existe uma taxa de balsa de '{payload.cidade_origem}' → '{payload.cidade_destino}' "
        f"pro veículo '{payload.veiculo}'.",
    )


@router.delete("/taxas-balsa/{id_}")
def admin_excluir_taxa_balsa(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_taxa_balsa, id_)


@router.get("/prioridades-rota")
def admin_listar_prioridades_rota(usuario: dict = Depends(exigir_admin)):
    return db.listar_prioridades_rota_admin()


@router.post("/prioridades-rota")
def admin_criar_prioridade_rota(payload: PrioridadeRotaIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(
        db.inserir_prioridade_rota, payload,
        f"Já existe uma prioridade de rota de '{payload.estado_origem}' → '{payload.cidade_destino}'.",
    )


@router.put("/prioridades-rota/{id_}")
def admin_atualizar_prioridade_rota(id_: int, payload: PrioridadeRotaIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(
        db.atualizar_prioridade_rota, id_, payload,
        f"Já existe uma prioridade de rota de '{payload.estado_origem}' → '{payload.cidade_destino}'.",
    )


@router.delete("/prioridades-rota/{id_}")
def admin_excluir_prioridade_rota(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_prioridade_rota, id_)


@router.get("/aliquotas-icms")
def admin_listar_aliquotas_icms(usuario: dict = Depends(exigir_admin)):
    return db.listar_aliquotas_icms_admin()


@router.post("/aliquotas-icms")
def admin_criar_aliquota_icms(payload: AliquotaIcmsIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(
        db.inserir_aliquota_icms, payload,
        f"Já existe uma alíquota de ICMS cadastrada de '{payload.estado_origem}' → '{payload.estado_destino}'.",
    )


@router.put("/aliquotas-icms/{id_}")
def admin_atualizar_aliquota_icms(id_: int, payload: AliquotaIcmsIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(
        db.atualizar_aliquota_icms, id_, payload,
        f"Já existe uma alíquota de ICMS cadastrada de '{payload.estado_origem}' → '{payload.estado_destino}'.",
    )


@router.delete("/aliquotas-icms/{id_}")
def admin_excluir_aliquota_icms(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_aliquota_icms, id_)


@router.get("/pracas-pedagio")
def admin_listar_pracas_pedagio(usuario: dict = Depends(exigir_admin)):
    return db.listar_pracas_pedagio_admin()


@router.post("/pracas-pedagio")
def admin_criar_praca_pedagio(payload: PracaPedagioIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(
        db.inserir_praca_pedagio, payload,
        f"Já existe uma praça de pedágio '{payload.nome}' na rodovia '{payload.rodovia}'.",
    )


@router.put("/pracas-pedagio/{id_}")
def admin_atualizar_praca_pedagio(id_: int, payload: PracaPedagioIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(
        db.atualizar_praca_pedagio, id_, payload,
        f"Já existe uma praça de pedágio '{payload.nome}' na rodovia '{payload.rodovia}'.",
    )


@router.delete("/pracas-pedagio/{id_}")
def admin_excluir_praca_pedagio(id_: int, usuario: dict = Depends(exigir_admin)):
    try:
        return admin_excluir(db.excluir_praca_pedagio, id_)
    except db.ConflitoIntegridade as exc:
        raise HTTPException(
            status_code=409,
            detail="Essa praça está em uso em algum pedágio de rota cadastrado — remova o vínculo antes de excluí-la.",
        ) from exc


@router.post("/pracas-pedagio/importar-csv")
def admin_importar_pracas_pedagio(payload: ImportarPracasPedagioRequest, usuario: dict = Depends(exigir_admin)):
    """Importa/atualiza o catálogo de praças a partir de um CSV no mesmo
    formato publicado pelas concessionárias — ver
    frete_db.importar_pracas_pedagio_csv para o formato esperado. Recebe o
    texto do arquivo já lido no navegador (não multipart), pra não
    depender do pacote python-multipart."""
    resultado = db.importar_pracas_pedagio_csv(payload.conteudo)
    fs.carregar_parametros()
    return resultado


@router.get("/pedagios-rota")
def admin_listar_pedagios_rota(usuario: dict = Depends(exigir_admin)):
    return db.listar_pedagios_rota_admin()


@router.post("/pedagios-rota")
def admin_criar_pedagio_rota(payload: PedagioRotaIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(
        db.inserir_pedagio_rota, payload,
        f"Já existe um pedágio de rota de '{payload.cidade_origem}' → '{payload.cidade_destino}' pra essa praça.",
    )


@router.put("/pedagios-rota/{id_}")
def admin_atualizar_pedagio_rota(id_: int, payload: PedagioRotaIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(
        db.atualizar_pedagio_rota, id_, payload,
        f"Já existe um pedágio de rota de '{payload.cidade_origem}' → '{payload.cidade_destino}' pra essa praça.",
    )


@router.delete("/pedagios-rota/{id_}")
def admin_excluir_pedagio_rota(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_pedagio_rota, id_)


@router.get("/distancias-fixas")
def admin_listar_distancias_fixas(usuario: dict = Depends(exigir_admin)):
    return db.listar_distancias_fixas_admin()


@router.post("/distancias-fixas")
def admin_criar_distancia_fixa(payload: DistanciaFixaIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(
        db.inserir_distancia_fixa, payload,
        f"Já existe uma distância fixa cadastrada de '{payload.cidade_origem}' → '{payload.cidade_destino}'.",
    )


@router.put("/distancias-fixas/{id_}")
def admin_atualizar_distancia_fixa(id_: int, payload: DistanciaFixaIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(
        db.atualizar_distancia_fixa, id_, payload,
        f"Já existe uma distância fixa cadastrada de '{payload.cidade_origem}' → '{payload.cidade_destino}'.",
    )


@router.delete("/distancias-fixas/{id_}")
def admin_excluir_distancia_fixa(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_distancia_fixa, id_)


@router.get("/transportadoras-terceirizadas")
def admin_listar_transportadoras_terceirizadas(usuario: dict = Depends(exigir_admin)):
    return db.listar_transportadoras_terceirizadas_admin()


@router.post("/transportadoras-terceirizadas")
def admin_criar_transportadora_terceirizada(payload: TransportadoraTerceirizadaIn, usuario: dict = Depends(exigir_admin)):
    # reload=False: transportadoras terceirizadas não fazem parte do
    # ParametrosFrete em memória (são lidas direto do banco quando
    # usadas), então recarregar o cache aqui não teria efeito nenhum.
    return admin_criar(
        db.inserir_transportadora_terceirizada, payload,
        f"Já existe uma transportadora '{payload.nome}' cadastrada para '{payload.cidade}'.",
        reload=False,
    )


@router.put("/transportadoras-terceirizadas/{id_}")
def admin_atualizar_transportadora_terceirizada(id_: int, payload: TransportadoraTerceirizadaIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(
        db.atualizar_transportadora_terceirizada, id_, payload,
        f"Já existe uma transportadora '{payload.nome}' cadastrada para '{payload.cidade}'.",
        reload=False,
    )


@router.delete("/transportadoras-terceirizadas/{id_}")
def admin_excluir_transportadora_terceirizada(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(db.excluir_transportadora_terceirizada, id_, reload=False)


@router.get("/faixas-coleta")
def admin_listar_faixas_coleta(usuario: dict = Depends(exigir_admin)):
    return db.listar_faixas_coleta()


@router.post("/faixas-coleta")
def admin_criar_faixa_coleta(payload: FaixaColetaIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(db.inserir_faixa_coleta, payload, "")


@router.put("/faixas-coleta/{id_}")
def admin_atualizar_faixa_coleta(id_: int, payload: FaixaColetaIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_faixa_coleta, id_, payload, "")


@router.delete("/faixas-coleta/{id_}")
def admin_excluir_faixa_coleta(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(
        db.excluir_faixa_coleta, id_, db.contar_faixas_coleta,
        "Não é possível excluir a última faixa de coleta cadastrada — o sistema precisa de pelo menos uma.",
    )


@router.get("/categorias")
def admin_listar_categorias(usuario: dict = Depends(exigir_admin)):
    return db.listar_categorias_admin()


@router.post("/categorias")
def admin_criar_categoria(payload: CategoriaIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(db.inserir_categoria, payload, f"Já existe uma categoria chamada '{payload.nome}'.")


@router.put("/categorias/{id_}")
def admin_atualizar_categoria(id_: int, payload: CategoriaIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_categoria, id_, payload, f"Já existe uma categoria chamada '{payload.nome}'.")


@router.delete("/categorias/{id_}")
def admin_excluir_categoria(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(
        db.excluir_categoria, id_, db.contar_categorias,
        "Não é possível excluir a última categoria cadastrada — o sistema precisa de pelo menos uma.",
    )


@router.get("/transportes")
def admin_listar_transportes(usuario: dict = Depends(exigir_admin)):
    return db.listar_transportes_admin()


@router.post("/transportes")
def admin_criar_transporte(payload: TransporteIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(db.inserir_transporte, payload, f"Já existe um transporte chamado '{payload.nome}'.")


@router.put("/transportes/{id_}")
def admin_atualizar_transporte(id_: int, payload: TransporteIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_transporte, id_, payload, f"Já existe um transporte chamado '{payload.nome}'.")


@router.delete("/transportes/{id_}")
def admin_excluir_transporte(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(
        db.excluir_transporte, id_, db.contar_transportes,
        "Não é possível excluir o último transporte cadastrado — o sistema precisa de pelo menos um.",
    )


@router.get("/slas")
def admin_listar_slas(usuario: dict = Depends(exigir_admin)):
    return db.listar_slas_admin()


@router.post("/slas")
def admin_criar_sla(payload: SlaIn, usuario: dict = Depends(exigir_admin)):
    return admin_criar(db.inserir_sla, payload, f"Já existe um SLA chamado '{payload.nome}'.")


@router.put("/slas/{id_}")
def admin_atualizar_sla(id_: int, payload: SlaIn, usuario: dict = Depends(exigir_admin)):
    return admin_atualizar(db.atualizar_sla, id_, payload, f"Já existe um SLA chamado '{payload.nome}'.")


@router.delete("/slas/{id_}")
def admin_excluir_sla(id_: int, usuario: dict = Depends(exigir_admin)):
    return admin_excluir(
        db.excluir_sla, id_, db.contar_slas,
        "Não é possível excluir o último SLA cadastrado — o sistema precisa de pelo menos um.",
    )
