"""
Gera os dados da página "Recursos CAPES por curso" a partir da planilha publicada.

O que faz:
  1. Baixa as abas de recursos e da matriz curso x recurso da planilha publicada.
  2. Gera o arquivo dados.json (só recursos com Status = Ativo) e o titulos.json
     (títulos de periódicos ativos, usados na busca de revistas).
  3. Atualiza a cópia de reserva dentro de index.html.

Como rodar (na pasta onde estão este script e o HTML):
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
from pathlib import Path

# ---------- CONFIGURAÇÃO ----------
PLANILHA = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vQQCO8sZ4oCALSf7vxBioerB0RLS4gcr-"
            "eI984cjQlx6LK7nZquk3j9GU6wEpwidppw4qox_V5U0qDf/pub?output=csv&gid=")
GID_RECURSOS = "1270713400"
GID_MATRIZ = "888514790"

PASTA = Path(__file__).resolve().parent
ARQUIVO_JSON = PASTA / "dados.json"
ARQUIVO_TITULOS = PASTA / "titulos.json"

# Planilha dos títulos de periódicos (compartilhada como "qualquer pessoa com o link")
PLANILHA_TITULOS = ("https://docs.google.com/spreadsheets/d/1SPPtYJG2Bzaht6hcoOgZF3lBGGv_Z9dHIz68otQvpp8/"
                    "export?format=csv&gid=1971989936")
ARQUIVO_HTML = PASTA / "index.html"

# Notas extras que aparecem no card do recurso (nome exato do recurso: texto)
NOTAS = {
    "Future Medicine Special Collection":
        'Para abrir os títulos, entre em tandfonline.com e use "Log in via your institution" escolhendo a UFCAT.',
}

# Linha da matriz que vale para todos os cursos
LINHA_TODOS = "Todos os cursos"
# ----------------------------------


def baixar_csv(gid=None, url=None):
    with urllib.request.urlopen(url or (PLANILHA + gid), timeout=120) as r:
        texto = r.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(texto)))


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
        chave = (titulo.lower(), colecao)
        if chave in vistos:
            continue
        vistos.add(chave)
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
                        (x.get("Cobertura") or "").strip(), url, "; ".join(temas)])
    titulos.sort(key=lambda r: r[0].lower())
    ARQUIVO_TITULOS.write_text(json.dumps({"colecoes": colecoes, "titulos": titulos}, ensure_ascii=False,
                                          separators=(",", ":")), encoding="utf-8")
    print(f"titulos.json gerado: {len(titulos)} títulos em {len(colecoes)} coleções.")
    fora = [c for c in colecoes if c not in colecoes_ativas]
    if fora:
        print("Coleções da planilha de títulos que não estão ativas na planilha de recursos:", "; ".join(fora))
    contagem = {}
    for linha in titulos:
        nome = colecoes[linha[1]]
        contagem[nome] = contagem.get(nome, 0) + 1
    return contagem


def slug(texto):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def resumir(descricao):
    primeira = str(descricao).split("\n")[0].strip()
    frase = re.split(r"(?<=[a-z\)])\. (?=[A-ZÁÉÍÓÚ])", primeira)[0]
    if not frase.endswith("."):
        frase += "."
    if len(frase) > 260:
        frase = frase[:250].rsplit(" ", 1)[0] + "…"
    return frase


def principal():
    print("Baixando a planilha...")
    recursos_brutos = baixar_csv(GID_RECURSOS)
    matriz = baixar_csv(GID_MATRIZ)

    recursos = []
    for x in recursos_brutos:
        nome = (x.get("Nome do Recurso") or "").strip()
        if not nome or (x.get("Status") or "").strip() != "Ativo":
            continue
        tutorial_txt = x.get("Tutoriais (CAPES)") or ""
        urls = re.findall(r"https?://\S+", tutorial_txt)
        urls = [u.rstrip(".") for u in urls if "tandfonline.com" not in u.lower()]
        preferidos = [u for u in urls if "periodicos.capes" in u]
        tutoriais = preferidos or urls
        descricao = (x.get("Descrição") or "").strip()
        recursos.append({
            "id": slug(nome)[:40],
            "nome": nome,
            "tipo": (x.get("Tipo") or "").strip(),
            "resumo": resumir(descricao),
            "desc": descricao,
            "tutorial": tutoriais[0] if tutoriais else "",
            "nota": NOTAS.get(nome, ""),
        })

    id_por_nome = {r["nome"]: r["id"] for r in recursos}
    por_curso = {}
    for linha in matriz:
        if str(linha.get("Disponível", "")).strip().upper() != "TRUE":
            continue
        rid = id_por_nome.get(linha.get("Recursos disponíveis"))
        if rid:
            por_curso.setdefault(linha["Cursos"].strip(), []).append(rid)

    chave_todos = next((k for k in por_curso if k.startswith(LINHA_TODOS)), None)
    geral = por_curso.pop(chave_todos, []) if chave_todos else []

    # quantas revistas cada coleção tem na planilha de títulos (para o botão "Ver as N revistas")
    contagem = gerar_titulos({r["nome"] for r in recursos})
    for r in recursos:
        if contagem.get(r["nome"]):
            r["revistas"] = contagem[r["nome"]]

    dados = {
        "recursos": recursos,
        "cursos": [{"nome": c, "slug": slug(c), "recursos": ids}
                   for c, ids in sorted(por_curso.items())],
        "geral": geral,
    }

    ARQUIVO_JSON.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"dados.json gerado: {len(recursos)} recursos ativos, {len(por_curso)} cursos.")

    sem_tutorial = [r["nome"] for r in recursos if not r["tutorial"]]
    if sem_tutorial:
        print("Recursos sem link de tutorial:", "; ".join(sem_tutorial))

    if not ARQUIVO_HTML.exists():
        print(f"Aviso: não encontrei {ARQUIVO_HTML.name} nesta pasta. Só o JSON foi gerado.")
        return
    with open(ARQUIVO_HTML, encoding="utf-8-sig", newline="") as f:
        html = f.read()
    compacto = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    # Aceita quebra de linha do Windows (CRLF) e dados quebrados em várias linhas:
    # troca tudo entre "const DADOS_RESERVA =" e a linha "const PLANILHA".
    padrao = re.compile(r"const DADOS_RESERVA\s*=[\s\S]*?;(?=\s*const PLANILHA\b)")
    novo, trocas = padrao.subn(lambda m: "const DADOS_RESERVA = " + compacto + ";", html, count=1)
    if trocas != 1:
        print("Erro: não encontrei o bloco 'const DADOS_RESERVA' seguido de 'const PLANILHA' no HTML.")
        print("Confira se o HTML é a versão original da página. Nada foi alterado no HTML.")
        sys.exit(1)
    # grava sem converter as quebras de linha existentes
    with open(ARQUIVO_HTML, "w", encoding="utf-8", newline="") as f:
        f.write(novo)
    print(f"{ARQUIVO_HTML.name} atualizado. Pronto para publicar.")


if __name__ == "__main__":
    try:
        principal()
    except Exception as erro:
        print("Não foi possível gerar os dados:", erro)
        print("Confira a internet e se a planilha continua publicada na web.")
        sys.exit(1)
