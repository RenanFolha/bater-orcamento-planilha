# Desenvolvedor Chefe: RenanFolha

"""Rotas públicas de leitura dos parâmetros cadastrados (sem exigir login) —
usadas para montar os campos de seleção da tela de orçamento."""

from fastapi import APIRouter

import frete_db as db
import frete_service as fs

router = APIRouter(prefix="/parametros", tags=["Parâmetros"])


@router.get("/categorias")
def listar_categorias():
    return [
        {"nome": c.nome, "multiplicador": c.multiplicador}
        for c in fs.parametros.categorias.values()
    ]


@router.get("/transportes")
def listar_transportes():
    return [
        {"nome": t.nome, "multiplicador": t.multiplicador, "fator_cubagem": t.fator_cubagem}
        for t in fs.parametros.transportes.values()
    ]


@router.get("/slas")
def listar_slas():
    return [
        {"nome": s.nome, "multiplicador": s.multiplicador, "prazo_dias": s.prazo_dias}
        for s in fs.parametros.slas.values()
    ]


@router.get("/filiais")
def listar_filiais():
    return [
        {"nome": f.nome, "endereco": f.endereco}
        for f in fs.parametros.filiais.values()
    ]


@router.get("/veiculos")
def listar_veiculos():
    return [
        {
            "nome": v.nome, "de": v.de, "ate": v.ate, "tarifa_km": v.tarifa_km,
            "valor_tonelada_excedente": v.valor_tonelada_excedente,
        }
        for v in fs.parametros.veiculos.values()
    ]


@router.get("/taxas-adicionais")
def listar_taxas_adicionais_publico():
    return [
        {"nome": t.nome, "tipo": t.tipo, "valor": t.valor}
        for t in fs.parametros.taxas_adicionais
    ]


@router.get("/tipos-frete")
def listar_tipos_frete():
    """Endpoint legado, mantido para compatibilidade com integrações que
    ainda leem as tabelas antigas de tipo de frete (faixas_peso/
    faixas_distancia) — não é mais usado no cálculo de orçamento, que
    hoje é baseado em veículo (ver /parametros/veiculos)."""
    tipos = {r["tipo_frete"] for r in db.listar_faixas_peso()}
    tipos |= {r["tipo_frete"] for r in db.listar_faixas_distancia()}
    return sorted(tipos)


@router.get("/faixas-peso")
def listar_faixas_peso_publico(tipo_frete: str | None = None):
    """Endpoint legado — ver nota em /parametros/tipos-frete."""
    faixas = db.listar_faixas_peso()
    if tipo_frete:
        faixas = [f for f in faixas if f["tipo_frete"] == tipo_frete]
    return [
        {
            "tipo_frete": f["tipo_frete"], "de": f["de"], "ate": f["ate"],
            "tarifa_base": f["tarifa_base"], "custo_kg_adicional": f["custo_kg_adicional"],
        }
        for f in faixas
    ]


@router.get("/faixas-distancia")
def listar_faixas_distancia_publico(tipo_frete: str | None = None):
    """Endpoint legado — ver nota em /parametros/tipos-frete."""
    faixas = db.listar_faixas_distancia()
    if tipo_frete:
        faixas = [f for f in faixas if f["tipo_frete"] == tipo_frete]
    return [
        {
            "tipo_frete": f["tipo_frete"], "de": f["de"], "ate": f["ate"],
            "taxa_fixa": f["taxa_fixa"], "tarifa_km": f["tarifa_km"],
        }
        for f in faixas
    ]


@router.get("/faixas-coleta")
def listar_faixas_coleta():
    return [
        {"de": f.de, "ate": f.ate, "taxa_fixa": f.taxa_fixa, "tarifa_km": f.tarifa_km}
        for f in fs.parametros.faixas_coleta
    ]


@router.get("/transportadoras-terceirizadas")
def listar_transportadoras_terceirizadas():
    """Lista as transportadoras terceirizadas cadastradas — usado pra
    montar o seletor na tela de orçamento quando coleta/entrega é
    terceirizada."""
    return db.listar_transportadoras_terceirizadas_admin()
