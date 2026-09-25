"""
Gera os dados da página "Recursos CAPES por curso" a partir da planilha publicada.

O que faz:
  1. Acha as abas da planilha publicada pelo nome (não depende do gid).
  2. Lê a aba principal (recursos), a aba "Cursos", a matriz "Curso e Recurso"
     (Essencial / Complementar / vazio) e a aba "Recurso ÁREA_CNPQ".
  3. Gera o dados.json (só recursos com Status = Ativo) e o titulos.json
     (títulos de periódicos ativos, usados na busca de revistas).
  4. Atualiza a cópia de reserva dentro do index.html e, se existir, a linha
     "const GIDS = {...};" com os gids atuais das abas.
  5. Avisa no terminal o que estiver incoerente na planilha.

Como rodar (na pasta onde estão este script e o index.html):
  python gerar_dados.py

Usa só bibliotecas que já vêm com o Python. Não precisa instalar nada.
"""

import csv
import io
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path

# ---------- CONFIGURAÇÃO ----------
PUBLICADA = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vQQCO8sZ4oCALSf7vxBioerB0RLS4gcr-"
             "eI984cjQlx6LK7nZquk3j9GU6wEpwidppw4qox_V5U0qDf")
PLANILHA = PUBLICADA + "/pub?output=csv&gid="

# Nome de cada aba na planilha e o gid conhecido (usado só se não der para achar pelo nome).
ABAS = {
    "recursos": ("Recursos por Área e Cursos Associados", "1270713400"),
    "matriz":   ("Curso e Recurso", "1969779059"),
    "areas":    ("Recurso ÁREA_CNPQ", "1774301612"),
    "cursos":   ("Cursos", ""),
}

PASTA = Path(__file__).resolve().parent
ARQUIVO_JSON = PASTA / "dados.json"
ARQUIVO_TITULOS = PASTA / "titulos.json"
ARQUIVO_HTML = PASTA / "index.html"

# Planilha dos títulos de periódicos (compartilhada como "qualquer pessoa com o link")
PLANILHA_TITULOS = ("https://docs.google.com/spreadsheets/d/1SPPtYJG2Bzaht6hcoOgZF3lBGGv_Z9dHIz68otQvpp8/"
                    "export?format=csv&gid=1971989936")

# Notas extras que aparecem no card do recurso (nome exato do recurso: texto)
NOTAS = {
    "Future Medicine Special Collection":
        'Para abrir os títulos, entre em tandfonline.com e use "Log in via your institution" escolhendo a UFCAT.',
}

# Linha da matriz que vale para todos os cursos
LINHA_TODOS = "Todos os cursos"
# Linhas da matriz e da aba de áreas que são totais, não dados
PREFIXO_TOTAL = "Quantos"
NIVEIS = {"essencial": "essenciais", "complementar": "complementares"}
# ----------------------------------

avisos = []


def aviso(texto):
    avisos.append(texto)


def chave(texto):
    """Compara nomes sem diferença de acento, maiúscula e espaços."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def slug(texto):
    return re.sub(r"[^a-z0-9]+", "-", chave(texto)).strip("-")


def baixar(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read().decode("utf-8-sig")


def baixar_csv(gid=None, url=None):
    return list(csv.DictReader(io.StringIO(baixar(url or (PLANILHA + gid)))))


def baixar_linhas(gid):
    """CSV como lista de listas (para a matriz, onde o cabeçalho são os nomes dos recursos)."""
    return list(csv.reader(io.StringIO(baixar(PLANILHA + gid))))


def descobrir_gids():
    """Lê a página publicada e devolve {nome da aba: gid}."""
    try:
        html = baixar(PUBLICADA + "/pubhtml")
    except Exception as erro:
        print("Não consegui ler a lista de abas publicadas:", erro)
        return {}
    achados = re.findall(r'items\.push\(\{name: "((?:[^"\\]|\\.)*)", pageUrl: "[^"]*?gid=(\d+)', html)
    return {chave(nome): gid for nome, gid in achados}


def gids_das_abas():
    publicadas = descobrir_gids()
    gids = {}
    for papel, (nome, reserva) in ABAS.items():
        gid = publicadas.get(chave(nome)) or reserva
        if not gid:
            print(f'Erro: não achei a aba "{nome}" na planilha publicada.')
            print('Confira o nome da aba e se a publicação está como "Documento inteiro".')
            sys.exit(1)
        if publicadas and chave(nome) not in publicadas:
            aviso(f'A aba "{nome}" não apareceu na lista de abas publicadas; usei o gid guardado ({gid}).')
        gids[papel] = gid
    return gids


def gerar_titulos(colecoes_ativas):
    """Gera titulos.json: só títulos Ativo, sem repetições, com temas principais e específicos juntos."""
    print("Baixando a planilha de títulos...")
    linhas = baixar_csv(url=PLANILHA_TITULOS)
    colecoes, indice, titulos, vistos = [], {}, [], set()
    for x in linhas:
        titulo = (x.get("Título") or "").strip()
        colecao = (x.get("Coleção de Periódicos") or "").strip()
        if not titulo or not colecao or (x.get("status") or "").strip() != "Ativo":
            continue
        ch = (titulo.lower(), colecao)
        if ch in vistos:
            continue
        vistos.add(ch)
        if colecao not in indice:
            indice[colecao] = len(colecoes)
            colecoes.append(colecao)
        url = (x.get("Url_Pagina_Inicial") or "").strip()
        if "periodicos.capes.gov.br" in url or not url.startswith("http"):
            url = ""  # sem link próprio: a página mostra "Buscar no Portal CAPES"
        temas = []
        for campo in ("Tópicos Principais", "Tópicos Específicos"):
            for tema in (x.get(campo) or "").split(";"):
                tema = tema.strip()
                if tema and tema not in temas:
                    temas.append(tema)
        titulos.append([titulo, indice[colecao], (x.get("ISSN") or "").strip(), (x.get("EISSN") or "").strip(),
                        (x.get("Cobertura") or "").strip(), url, "; ".join(temas),
                        (x.get("Editora") or "").strip()])
    titulos.sort(key=lambda r: r[0].lower())
    ARQUIVO_TITULOS.write_text(json.dumps({"colecoes": colecoes, "titulos": titulos}, ensure_ascii=False,
                                          separators=(",", ":")), encoding="utf-8")
    print(f"titulos.json gerado: {len(titulos)} títulos em {len(colecoes)} coleções.")
    fora = [c for c in colecoes if c not in colecoes_ativas]
    if fora:
        aviso("Coleções da planilha de títulos que não estão ativas na planilha de recursos: " + "; ".join(fora))
    contagem = {}
    for linha in titulos:
        nome = colecoes[linha[1]]
        contagem[nome] = contagem.get(nome, 0) + 1
    return contagem


def resumir(descricao):
    primeira = str(descricao).split("\n")[0].strip()
    frase = re.split(r"(?<=[a-z\)])\. (?=[A-ZÁÉÍÓÚ])", primeira)[0]
    if not frase.endswith("."):
        frase += "."
    if len(frase) > 260:
        frase = frase[:250].rsplit(" ", 1)[0] + "…"
    return frase


def ler_recursos(gid):
    recursos, todos_nomes = [], set()
    for x in baixar_csv(gid):
        nome = (x.get("Nome do Recurso") or "").strip()
        if not nome or not (x.get("Tipo") or "").strip():
            continue
        todos_nomes.add(nome)
        if (x.get("Status") or "").strip() != "Ativo":
            continue
        tutorial_txt = x.get("Tutoriais (CAPES)") or ""
        urls = [u.rstrip(".") for u in re.findall(r"https?://\S+", tutorial_txt) if "tandfonline.com" not in u.lower()]
        tutoriais = [u for u in urls if "periodicos.capes" in u] or urls
        descricao = (x.get("Descrição") or "").strip()
        recursos.append({
            "id": slug(nome)[:40],
            "nome": nome,
            "tipo": (x.get("Tipo") or "").strip(),
            "resumo": resumir(descricao),
            "desc": descricao,
            "tutorial": tutoriais[0] if tutoriais else "",
            "nota": NOTAS.get(nome, ""),
            "areas": [],
        })
    return recursos, todos_nomes


def ler_areas(gid, por_nome):
    """Aba Recurso ÁREA_CNPQ: uma coluna por área, TRUE/FALSE."""
    linhas = baixar_linhas(gid)
    cab = linhas[0]
    colunas = [(i, c.strip()) for i, c in enumerate(cab) if i > 0 and c.strip() and not c.strip().startswith("Áreas (texto)")]
    ordem = [nome for _, nome in colunas]
    for linha in linhas[1:]:
        if not linha or not linha[0].strip() or linha[0].startswith(PREFIXO_TOTAL):
            continue
        nome = linha[0].strip()
        rec = por_nome.get(chave(nome))
        if rec is None:
            continue  # recurso inativo ou nome de outra versão: tratado no aviso da matriz
        rec["areas"] = [area for i, area in colunas if i < len(linha) and linha[i].strip().upper() == "TRUE"]
    return ordem


def ler_cursos(gid):
    info = {}
    for x in baixar_csv(gid):
        nome = (x.get("Curso") or "").strip()
        if not nome:
            continue
        info[chave(nome)] = {
            "nivel": (x.get("Nível") or "").strip(),
            "area": (x.get("Área CNPq") or "").strip(),
            "termos": (x.get("Termos de busca") or "").strip(),
            "antigos": [slug(n) for n in (x.get("Nomes antigos") or "").split(";") if n.strip()],
            "nome": nome,
        }
    return info


def ler_matriz(gid, por_nome, todos_nomes):
    linhas = baixar_linhas(gid)
    cab = [c.strip() for c in linhas[0]]
    colunas = []  # (índice, id do recurso ativo ou None)
    for i, nome in enumerate(cab[1:], 1):
        if not nome:
            continue
        rec = por_nome.get(chave(nome))
        if rec:
            colunas.append((i, rec["id"]))
        elif nome in todos_nomes:
            colunas.append((i, None))  # recurso inativo: ignora sem avisar
        elif nome not in ("Essenciais", "Complementares") and not nome.startswith(PREFIXO_TOTAL):
            aviso(f'Coluna "{nome}" da matriz não existe na aba principal. Confira o nome.')
    cursos, geral = {}, []
    for linha in linhas[1:]:
        if not linha or not linha[0].strip() or linha[0].startswith(PREFIXO_TOTAL):
            continue
        nome = linha[0].strip()
        niveis = {"essenciais": [], "complementares": []}
        for i, rid in colunas:
            valor = linha[i].strip() if i < len(linha) else ""
            if not valor or valor.upper() == "FALSE":
                continue
            grupo = NIVEIS.get(chave(valor))
            if grupo is None:
                aviso(f'Valor "{valor}" em "{nome}" x "{cab[i]}". Use Essencial, Complementar ou deixe vazio.')
                continue
            if rid:
                niveis[grupo].append(rid)
        if nome.startswith(LINHA_TODOS):
            geral = niveis["essenciais"] + niveis["complementares"]
        else:
            cursos[nome] = niveis
    return cursos, geral


def principal():
    print("Localizando as abas publicadas...")
    gids = gids_das_abas()
    print("Baixando a planilha...")
    recursos, todos_nomes = ler_recursos(gids["recursos"])
    por_nome = {chave(r["nome"]): r for r in recursos}
    ordem_areas = ler_areas(gids["areas"], por_nome)
    info_cursos = ler_cursos(gids["cursos"])
    matriz, geral = ler_matriz(gids["matriz"], por_nome, todos_nomes)

    cursos = []
    for nome, niveis in matriz.items():
        info = info_cursos.get(chave(nome))
        if info is None:
            aviso(f'Curso "{nome}" está na matriz mas não na aba Cursos.')
            info = {"nivel": "", "area": "", "termos": "", "antigos": []}
        geral_set = set(geral)
        ess = [r for r in niveis["essenciais"] if r not in geral_set]
        comp = [r for r in niveis["complementares"] if r not in geral_set and r not in ess]
        if not ess:
            aviso(f'Curso "{nome}" está sem nenhum recurso essencial.')
        if info["area"] and info["area"] not in ordem_areas:
            aviso(f'Área "{info["area"]}" do curso "{nome}" não bate com as colunas da aba de áreas.')
        cursos.append({
            "nome": nome, "slug": slug(nome), "area": info["area"], "nivel": info["nivel"],
            "termos": info["termos"], "antigos": info["antigos"],
            "essenciais": ess, "complementares": comp,
            "recursos": ess + comp,  # lista única, mantida para compatibilidade
        })
    nomes_matriz = {chave(c["nome"]) for c in cursos}
    for ch, info in info_cursos.items():
        if ch not in nomes_matriz:
            aviso(f'Curso "{info["nome"]}" está na aba Cursos mas não na matriz.')
    cursos.sort(key=lambda c: chave(c["nome"]))

    usados = set(geral) | {rid for c in cursos for rid in c["recursos"]}
    for r in recursos:
        if not r["areas"]:
            aviso(f'Recurso ativo sem área marcada: {r["nome"]}.')
        if r["id"] not in usados:
            aviso(f'Recurso ativo sem nenhum curso (aparece só na busca por área): {r["nome"]}.')

    contagem = gerar_titulos({r["nome"] for r in recursos})
    for r in recursos:
        if contagem.get(r["nome"]):
            r["revistas"] = contagem[r["nome"]]

    dados = {
        "atualizado": date.today().isoformat(),
        "areas": [a for a in ordem_areas if a != "Multidisciplinar"],
        "recursos": recursos,
        "cursos": cursos,
        "geral": geral,
    }
    ARQUIVO_JSON.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"dados.json gerado: {len(recursos)} recursos ativos, {len(cursos)} cursos, {len(geral)} bases gerais.")

    sem_tutorial = [r["nome"] for r in recursos if not r["tutorial"]]
    if sem_tutorial:
        aviso("Recursos sem link de tutorial: " + "; ".join(sem_tutorial))

    atualizar_html(dados, gids)

    if avisos:
        print(f"\nConfira na planilha ({len(avisos)}):")
        for a in avisos:
            print("  -", a)
    else:
        print("\nNada a conferir na planilha.")


def atualizar_html(dados, gids):
    if not ARQUIVO_HTML.exists():
        print(f"Aviso: não encontrei {ARQUIVO_HTML.name} nesta pasta. Só os JSON foram gerados.")
        return
    with open(ARQUIVO_HTML, encoding="utf-8-sig", newline="") as f:
        html = f.read()
    compacto = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    # troca tudo entre "const DADOS_RESERVA =" e a linha "const PLANILHA"
    padrao = re.compile(r"const DADOS_RESERVA\s*=[\s\S]*?;(?=\s*const PLANILHA\b)")
    novo, trocas = padrao.subn(lambda m: "const DADOS_RESERVA = " + compacto + ";", html, count=1)
    if trocas != 1:
        print("Erro: não encontrei o bloco 'const DADOS_RESERVA' seguido de 'const PLANILHA' no HTML.")
        print("Confira se o HTML é a versão original da página. Nada foi alterado no HTML.")
        sys.exit(1)
    linha_gids = "const GIDS = " + json.dumps(gids, ensure_ascii=False) + ";"
    novo, trocas_gids = re.subn(r"const GIDS\s*=\s*\{[^}]*\};", lambda m: linha_gids, novo, count=1)
    if not trocas_gids:
        print("Obs.: o HTML ainda não tem a linha 'const GIDS = {...};'. Os gids não foram atualizados nele.")
    with open(ARQUIVO_HTML, "w", encoding="utf-8", newline="") as f:
        f.write(novo)
    print(f"{ARQUIVO_HTML.name} atualizado. Pronto para publicar.")


if __name__ == "__main__":
    try:
        principal()
    except SystemExit:
        raise
    except Exception as erro:
        print("Não foi possível gerar os dados:", erro)
        print("Confira a internet e se a planilha continua publicada na web.")
        sys.exit(1)
