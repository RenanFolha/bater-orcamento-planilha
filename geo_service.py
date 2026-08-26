"""
Calcula distâncias rodoviárias entre endereços/filiais.

Se a variável de ambiente GOOGLE_MAPS_API_KEY estiver configurada, usa a
Geocoding API + Distance Matrix API do Google Maps (mais tolerante a
endereços incompletos/bagunçados). Caso contrário, cai automaticamente
nos serviços gratuitos e sem chave:

- Nominatim (OpenStreetMap) para geocodificar endereços (texto -> lat/lon)
- OSRM (Open Source Routing Machine) para calcular a distância de rota
  rodoviária entre duas coordenadas

Também resolve qual filial cadastrada fica mais perto de um endereço de
retirada/entrega (usando distância em linha reta para escolher a
candidata, e só então uma chamada de rota real para o resultado final).
"""

import math
import os
import re
from collections import OrderedDict

import httpx

import frete_db as db
import frete_service as fs

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL_TEMPLATE = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"

GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

USER_AGENT = os.environ.get(
    "GEO_USER_AGENT", "SistemaOrcamentoFrete/1.0 (uso interno da empresa)"
)
COUNTRY_CODES = os.environ.get("GEO_COUNTRY_CODES", "br")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()


def usando_google() -> bool:
    return bool(GOOGLE_MAPS_API_KEY)

# LRU limitado: endereços de cliente digitados em texto livre são
# praticamente ilimitados (ao contrário da lista fixa de filiais), então
# sem um teto o cache cresceria sem parar pela vida do processo.
_GEOCODE_CACHE_MAX = 500
_geocode_cache: "OrderedDict[str, tuple[float, float, str]]" = OrderedDict()


def _geocode_cache_get(chave: str) -> tuple[float, float, str] | None:
    if chave not in _geocode_cache:
        return None
    _geocode_cache.move_to_end(chave)
    return _geocode_cache[chave]


def _geocode_cache_set(chave: str, valor: tuple[float, float, str]) -> None:
    _geocode_cache[chave] = valor
    _geocode_cache.move_to_end(chave)
    if len(_geocode_cache) > _GEOCODE_CACHE_MAX:
        _geocode_cache.popitem(last=False)


class GeoError(Exception):
    """Erro ao geocodificar um endereço ou calcular a rota entre eles."""


_QUALIFICADORES_UNIDADE = re.compile(
    r"\b(bloco|galp[aã]o|pr[eé]dio|sala|quadra|lote|cond(?:om[ií]nio)?|conjunto|cj\.?|"
    r"apto?\.?|apartamento|km|kit\.?)\s*[\w°º-]*",
    re.IGNORECASE,
)
# "bairro X" é só um rótulo em português — mas o Nominatim não ignora a
# palavra "bairro" ao comparar, então "bairro Distrito Industrial" não dá
# nenhum resultado mesmo quando "Distrito Industrial" sozinho resolveria
# normalmente. Removemos o rótulo antes de montar as variantes de busca.
_PREFIXO_BAIRRO = re.compile(r"^bairro\s*:?\s*", re.IGNORECASE)
_CEP_REGEX = re.compile(r"(\d{2})\.?(\d{3})-?\s*(\d{3})")


def _extrair_cep(endereco: str) -> str | None:
    m = _CEP_REGEX.search(endereco)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}-{m.group(3)}"


def _variantes_endereco(endereco: str, dica_cidade: str | None = None) -> list[str]:
    """Gera variações progressivamente mais simples do endereço digitado,
    para tentar quando a busca literal falha no serviço de mapas (ex:
    endereços com "(Zona Sul)", "Bloco B - 4º Andar", bairro incomum,
    CEP embutido no texto, ou sem cidade/UF explícitos)."""
    variantes = [endereco]

    # 0) Trata "/" como separador de segmento também (comum em endereços
    # de filial no formato "..., bairro X / CEP: 00000-000")
    normalizado = endereco.replace("/", ",")

    # 1) Remove trechos entre parênteses, ex: "(Zona Sul)"
    sem_parenteses = re.sub(r"\([^)]*\)", "", normalizado)
    sem_parenteses = re.sub(r"\s{2,}", " ", sem_parenteses).strip()
    sem_parenteses = re.sub(r",\s*,", ",", sem_parenteses).strip(" ,")
    if sem_parenteses and sem_parenteses.lower() != endereco.strip().lower():
        variantes.append(sem_parenteses)

    base = sem_parenteses or normalizado
    partes = [p.strip() for p in base.split(",") if p.strip()]
    # remove segmentos que só falam de CEP (ex: "CEP: 02.701-000")
    partes_sem_cep = [p for p in partes if not re.search(r"\bcep\b", p, re.IGNORECASE)]
    # remove o rótulo "bairro" de cada segmento (ver _PREFIXO_BAIRRO)
    partes_sem_cep = [_PREFIXO_BAIRRO.sub("", p).strip() for p in partes_sem_cep]

    # 2) Rua + último segmento (bairro/cidade), removendo o miolo (números
    # de unidade, complementos) que costuma confundir o geocodificador
    if len(partes_sem_cep) > 2:
        variantes.append(f"{partes_sem_cep[0]}, {partes_sem_cep[-1]}")

    # 3) Mesma coisa, mas removendo qualificadores de unidade (Bloco,
    # Galpão, Sala, Km, Prédio, Quadra, Lote...) do primeiro segmento —
    # e tenta também só a rua sozinha (sem bairro/complemento nenhum):
    # um bairro com nome/grafia que o geocodificador não reconhece pode
    # fazer a busca inteira falhar mesmo com a rua certa.
    if partes_sem_cep:
        rua_limpa = _QUALIFICADORES_UNIDADE.sub("", partes_sem_cep[0])
        rua_limpa = re.sub(r"\s{2,}", " ", rua_limpa).strip(" ,-") or partes_sem_cep[0]
        if len(partes_sem_cep) >= 2:
            if rua_limpa.lower() != partes_sem_cep[0].lower():
                variantes.append(f"{rua_limpa}, {partes_sem_cep[-1]}")
            variantes.append(rua_limpa)
        elif rua_limpa.lower() != partes_sem_cep[0].lower():
            variantes.append(rua_limpa)

    # 4) Se foi passada uma dica de cidade (ex: nome cadastrado da filial,
    # que normalmente é a própria cidade) e ela ainda não aparece no
    # texto, acrescenta essa dica a cada variante — costuma resolver
    # endereços que têm rua/bairro mas não citam a cidade.
    if dica_cidade:
        cidade_norm = dica_cidade.strip()
        com_dica = []
        for v in list(variantes):
            if cidade_norm.lower() not in v.lower():
                com_dica.append(f"{v}, {cidade_norm}, Brasil")
        variantes.extend(com_dica)

    # remove duplicatas mantendo a ordem
    vistos = set()
    resultado = []
    for v in variantes:
        chave = v.strip().lower()
        if chave and chave not in vistos:
            vistos.add(chave)
            resultado.append(v.strip())
    return resultado


async def _tentar_busca(client: httpx.AsyncClient, params_extra: dict) -> list:
    params = {"format": "json", "limit": 1, **params_extra}
    resp = await client.get(
        NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=10
    )
    resp.raise_for_status()
    return resp.json()


async def _geocode_nominatim(client: httpx.AsyncClient, params_extra: dict) -> tuple[float, float, str] | None:
    resultados = await _tentar_busca(client, params_extra)
    if not resultados:
        return None
    r = resultados[0]
    return float(r["lat"]), float(r["lon"]), r.get("display_name")


async def _geocode_google(client: httpx.AsyncClient, texto: str) -> tuple[float, float, str] | None:
    params = {"address": texto, "key": GOOGLE_MAPS_API_KEY}
    if COUNTRY_CODES:
        params["region"] = COUNTRY_CODES
        params["components"] = f"country:{COUNTRY_CODES.upper()}"

    resp = await client.get(GOOGLE_GEOCODE_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")

    if status == "OK" and data.get("results"):
        r = data["results"][0]
        loc = r["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"]), r.get("formatted_address", texto)

    if status in ("ZERO_RESULTS", "INVALID_REQUEST"):
        return None

    # Erros de configuração (chave inválida, API não ativada, cota
    # estourada etc.) — não adianta tentar variações, então já avisa.
    raise GeoError(
        f"Google Maps recusou a consulta de geocodificação (status: {status}). "
        "Confira se a chave em GOOGLE_MAPS_API_KEY está correta e se a "
        "Geocoding API está ativada no Google Cloud Console."
    )


async def _geocode(
    client: httpx.AsyncClient, endereco: str, dica_cidade: str | None = None
) -> tuple[float, float, str]:
    chave = endereco.strip().lower()
    cacheado = _geocode_cache_get(chave)
    if cacheado is not None:
        return cacheado

    erro_conexao = None
    erro_provedor = None
    cep = _extrair_cep(endereco)
    textos = _variantes_endereco(endereco, dica_cidade=dica_cidade)

    if usando_google():
        tentativas_texto = list(textos)
        if cep and cep not in tentativas_texto:
            tentativas_texto.append(f"{cep}, Brasil")

        for texto in tentativas_texto:
            try:
                resultado = await _geocode_google(client, texto)
            except httpx.HTTPError:
                erro_conexao = GeoError(
                    f"Falha ao consultar o Google Maps para o endereço '{endereco}'."
                )
                continue
            except GeoError as e:
                # Erro de configuração da chave — não adianta insistir nas
                # demais variações, mas guarda pra reportar no final.
                erro_provedor = e
                break

            if resultado:
                lat, lon, nome_resolvido = resultado
                _geocode_cache_set(chave, (lat, lon, nome_resolvido))
                return lat, lon, nome_resolvido
    else:
        # Monta a lista de tentativas: primeiro variações do texto livre,
        # depois (se houver CEP no endereço) uma busca estruturada só pelo
        # CEP — mais confiável que jogar o CEP dentro do texto livre.
        tentativas: list[dict] = []
        for texto in textos:
            params_texto = {"q": texto}
            if COUNTRY_CODES:
                params_texto["countrycodes"] = COUNTRY_CODES
            tentativas.append(params_texto)
        if cep:
            tentativas.append({"postalcode": cep, "country": "Brazil"})

        for params_extra in tentativas:
            try:
                resultado = await _geocode_nominatim(client, params_extra)
            except httpx.HTTPError:
                erro_conexao = GeoError(
                    f"Falha ao consultar o serviço de mapas para o endereço '{endereco}'."
                )
                continue

            if resultado:
                lat, lon, nome_resolvido = resultado
                _geocode_cache_set(chave, (lat, lon, nome_resolvido))
                return lat, lon, nome_resolvido

    if erro_provedor:
        raise erro_provedor
    if erro_conexao:
        raise erro_conexao

    raise GeoError(
        f"Endereço não encontrado: \"{endereco}\". "
        "Tente ser mais específico (rua, número, cidade, UF) ou informe a distância manualmente."
    )


async def _rota_osrm(client: httpx.AsyncClient, lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    url = OSRM_URL_TEMPLATE.format(lon1=lon1, lat1=lat1, lon2=lon2, lat2=lat2)
    try:
        resp = await client.get(url, params={"overview": "false"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise GeoError(
            "Falha ao calcular a rota entre os pontos. Tente novamente ou informe a distância manualmente."
        ) from e

    if data.get("code") != "Ok" or not data.get("routes"):
        raise GeoError("Não foi possível calcular uma rota rodoviária entre os pontos informados.")

    rota = data["routes"][0]
    return {
        "distancia_km": round(rota["distance"] / 1000),
        "duracao_min": round(rota["duration"] / 60),
        # OSRM (gratuito) não calcula pedágio — só a Routes API do Google faz isso.
        "pedagio_valor": None,
        "pedagio_moeda": None,
    }


async def _rota_google(client: httpx.AsyncClient, lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    """Usa a Routes API (não a Distance Matrix) porque só ela traz
    estimativa de pedágio (routes.travelAdvisory.tollInfo) junto com a
    distância/duração, numa única chamada."""
    body = {
        "origin": {"location": {"latLng": {"latitude": lat1, "longitude": lon1}}},
        "destination": {"location": {"latLng": {"latitude": lat2, "longitude": lon2}}},
        "travelMode": "DRIVE",
        "extraComputations": ["TOLLS"],
        "routeModifiers": {"vehicleInfo": {"emissionType": "GASOLINE"}},
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.travelAdvisory.tollInfo",
    }
    try:
        resp = await client.post(GOOGLE_ROUTES_URL, json=body, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise GeoError(
            "Falha ao calcular a rota entre os pontos (Google Maps). "
            "Tente novamente ou informe a distância manualmente."
        ) from e

    rotas = data.get("routes")
    if not rotas:
        raise GeoError(
            "Não foi possível calcular uma rota rodoviária entre os pontos informados (Google Maps). "
            "Confira se a Routes API está ativada no Google Cloud Console."
        )

    rota = rotas[0]
    duracao_str = str(rota.get("duration", "0s"))
    duracao_seg = float(duracao_str[:-1]) if duracao_str.endswith("s") else float(duracao_str)

    resultado = {
        "distancia_km": round(rota.get("distanceMeters", 0) / 1000),
        "duracao_min": round(duracao_seg / 60),
        "pedagio_valor": None,
        "pedagio_moeda": None,
    }

    toll_info = (rota.get("travelAdvisory") or {}).get("tollInfo")
    precos = (toll_info or {}).get("estimatedPrice") or []
    if precos:
        # Normalmente só vem um valor, já na moeda local (BRL). O formato
        # Money do Google separa a parte inteira ("units") da fracionária
        # ("nanos", em bilionésimos), por isso a conta abaixo.
        preco = precos[0]
        units = int(preco.get("units", 0))
        nanos = int(preco.get("nanos", 0))
        resultado["pedagio_valor"] = round(units + nanos / 1_000_000_000, 2)
        resultado["pedagio_moeda"] = preco.get("currencyCode")

    return resultado


async def _rota(client: httpx.AsyncClient, lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    if usando_google():
        return await _rota_google(client, lat1, lon1, lat2, lon2)
    return await _rota_osrm(client, lat1, lon1, lat2, lon2)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distância em linha reta (aproximada) entre duas coordenadas, em km.
    Usada só para RANQUEAR qual filial está mais perto — a distância final
    exibida/cobrada sempre vem da rota real calculada pelo OSRM."""
    R = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


async def coordenadas_filial(client: httpx.AsyncClient, filial) -> tuple[float, float]:
    """Retorna (lat, lon) da filial, geocodificando e cacheando no banco se necessário."""
    if filial.latitude is not None and filial.longitude is not None:
        return filial.latitude, filial.longitude

    lat, lon, _ = await _geocode(client, filial.endereco, dica_cidade=filial.nome)
    db.atualizar_coordenadas_filial(filial.nome, lat, lon)
    filial.latitude, filial.longitude = lat, lon
    return lat, lon


# Velocidade média assumida só pra estimar a duração quando a distância vem
# reaproveitada do histórico (ver _buscar_rota_no_historico) — nesse caso
# não existe rota real calculada, então não tem duração de verdade
# disponível; é só uma estimativa grosseira pra não deixar o campo "0 min"
# no formulário. A distância em si (o que importa pro preço) é exata,
# vem de uma cotação anterior de verdade.
_VELOCIDADE_MEDIA_KMH = 60


def _buscar_rota_no_historico(origem: str, destino: str, veiculo: str | None) -> dict | None:
    """Se essa mesma rota (por cidade de origem/destino, nas duas direções —
    o negócio já trata ida e volta com a mesma distância, ver tabela de
    frete) E o mesmo veículo já foram cotados juntos e salvos no histórico
    antes, devolve a distância daquele registro (o mais recente) em vez de
    precisar chamar o serviço de geolocalização de novo. Evita gastar
    geocodificação/rota externa (rate limit do Nominatim/OSRM, ou custo do
    Google Maps) numa rota já conhecida.

    Sem o veículo não dá pra reaproveitar (retorna None sempre): pedágio
    varia por categoria de veículo, e é isso que vai ser cacheado junto com
    a distância mais adiante — então rota+veículo diferentes contam como
    "não é a mesma cotação", mesmo que a rota geográfica seja idêntica."""
    if not veiculo or not veiculo.strip():
        return None
    veiculo_alvo = veiculo.strip().lower()

    cidade_o, _ = fs.cidade_e_uf(origem)
    cidade_d, _ = fs.cidade_e_uf(destino)
    if not cidade_o or not cidade_d:
        return None
    cidade_o, cidade_d = cidade_o.strip().lower(), cidade_d.strip().lower()

    for rota in db.listar_rotas_historico():
        if (rota["veiculo"] or "").strip().lower() != veiculo_alvo:
            continue
        cidade_ro, _ = fs.cidade_e_uf(rota["origem_resumo"] or "")
        cidade_rd, _ = fs.cidade_e_uf(rota["destino_resumo"] or "")
        if not cidade_ro or not cidade_rd:
            continue
        cidade_ro, cidade_rd = cidade_ro.strip().lower(), cidade_rd.strip().lower()
        mesma_rota = (cidade_ro, cidade_rd) == (cidade_o, cidade_d)
        rota_invertida = (cidade_ro, cidade_rd) == (cidade_d, cidade_o)
        if mesma_rota or rota_invertida:
            return rota
    return None


async def calcular_distancia(origem: str, destino: str, veiculo: str | None = None) -> dict:
    """Distância rodoviária entre dois endereços em texto livre. Antes de
    chamar o serviço de geolocalização, verifica se essa rota + veículo já
    foi cotada e salva no histórico — se achar, reaproveita a distância de
    lá (silenciosamente, sem indicar isso na resposta) em vez de
    geocodificar de novo. Sem o veículo (chamador não informou), sempre
    geocodifica de verdade."""
    if not origem or not origem.strip():
        raise GeoError("Endereço de origem não informado.")
    if not destino or not destino.strip():
        raise GeoError("Endereço de destino não informado.")

    reaproveitada = _buscar_rota_no_historico(origem, destino, veiculo)
    if reaproveitada is not None:
        distancia_km = reaproveitada["distancia_km"]
        return {
            "distancia_km": distancia_km,
            "duracao_min": round(distancia_km / _VELOCIDADE_MEDIA_KMH * 60),
            "pedagio_valor": None,
            "pedagio_moeda": None,
            "origem_resolvido": reaproveitada["origem_resumo"],
            "destino_resolvido": reaproveitada["destino_resumo"],
        }

    async with httpx.AsyncClient() as client:
        lat1, lon1, nome1 = await _geocode(client, origem)
        lat2, lon2, nome2 = await _geocode(client, destino)
        rota = await _rota(client, lat1, lon1, lat2, lon2)

    return {
        **rota,
        "origem_resolvido": nome1,
        "destino_resolvido": nome2,
    }


async def resolver_retirada(endereco_retirada: str, filiais: list) -> dict:
    """Geocodifica o endereço de retirada, acha a filial mais próxima (dentre
    as cadastradas) e calcula a distância de rota real até ela."""
    if not endereco_retirada or not endereco_retirada.strip():
        raise GeoError("Endereço de retirada não informado.")
    if not filiais:
        raise GeoError("Nenhuma filial cadastrada para calcular a coleta.")

    async with httpx.AsyncClient() as client:
        lat_r, lon_r, nome_resolvido = await _geocode(client, endereco_retirada)

        # Ranqueia as filiais por distância em linha reta (rápido, sem gastar
        # chamadas de rota em todas elas) e usa a rota real só para a mais próxima.
        candidatas = []
        for filial in filiais:
            lat_f, lon_f = await coordenadas_filial(client, filial)
            dist_linha_reta = _haversine_km(lat_r, lon_r, lat_f, lon_f)
            candidatas.append((dist_linha_reta, filial, lat_f, lon_f))

        candidatas.sort(key=lambda c: c[0])
        _, filial_mais_proxima, lat_f, lon_f = candidatas[0]

        rota = await _rota(client, lat_f, lon_f, lat_r, lon_r)

    return {
        "filial_mais_proxima": filial_mais_proxima.nome,
        "filial_endereco": filial_mais_proxima.endereco,
        "distancia_coleta_km": rota["distancia_km"],
        "duracao_coleta_min": rota["duracao_min"],
        "endereco_resolvido": nome_resolvido,
    }