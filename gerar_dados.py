"""
Gera os dados da página "Recursos CAPES por curso" a partir da planilha publicada.

O que faz:
  1. Baixa as abas de recursos e da matriz curso x recurso da planilha publicada.
  2. Gera o arquivo dados.json (só recursos com Status = Ativo).
  3. Atualiza a cópia de reserva dentro de recursos-capes-ufcat.html.

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
ARQUIVO_HTML = PASTA / "recursos-capes-ufcat.html"

# Notas extras que aparecem no card do recurso (nome exato do recurso: texto)
NOTAS = {
    "Future Medicine Special Collection":
        'Para abrir os títulos, entre em tandfonline.com e use "Log in via your institution" escolhendo a UFCAT.',
}

# Linha da matriz que vale para todos os cursos
LINHA_TODOS = "Todos os cursos"
# ----------------------------------


def baixar_csv(gid):
    with urllib.request.urlopen(PLANILHA + gid, timeout=60) as r:
        texto = r.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(texto)))


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
    html = ARQUIVO_HTML.read_text(encoding="utf-8")
    compacto = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    novo, trocas = re.subn(r"^const DADOS_RESERVA = .*;$",
                           lambda m: "const DADOS_RESERVA = " + compacto + ";",
                           html, count=1, flags=re.M)
    if trocas != 1:
        print("Erro: não encontrei a linha 'const DADOS_RESERVA' no HTML. Nada foi alterado no HTML.")
        sys.exit(1)
    ARQUIVO_HTML.write_text(novo, encoding="utf-8")
    print(f"{ARQUIVO_HTML.name} atualizado. Pronto para publicar.")


if __name__ == "__main__":
    try:
        principal()
    except Exception as erro:
        print("Não foi possível gerar os dados:", erro)
        print("Confira a internet e se a planilha continua publicada na web.")
        sys.exit(1)
