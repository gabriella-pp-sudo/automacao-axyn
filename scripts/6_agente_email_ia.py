"""
AXYN Prospector — Script 6: Agente IA de E-mail
=================================================
Monitora a caixa de entrada do Gmail a cada 2 minutos.
Quando um lead responde, a IA (GPT-4o) elabora e envia a resposta automaticamente,
mantendo o histórico da conversa na planilha.

MESMOS GATILHOS DE PAUSA DO SCRIPT 3 (P1–P7):
  P1 → Lead quer fechar / comprar
  P2 → Pedido de desconto
  P3 → Tom agressivo ou hostil
  P4 → Pediu serviço fora do escopo
  P5 → Pediu para falar com humano
  P6 → Valor acima de R$ 3.000
  P7 → Contexto que a IA não sabe responder

VARIÁVEIS DE AMBIENTE NECESSÁRIAS:
  EMAIL_REMETENTE  → seuemail@gmail.com
  EMAIL_SENHA      → senha de app do Gmail (16 caracteres)
  OPENAI_API_KEY   → sua chave da OpenAI
  EMAIL_OPERADOR   → e-mail que recebe notificações de pausa (opcional, padrão: EMAIL_REMETENTE)

EXECUÇÃO:
  python scripts/6_agente_email_ia.py
  (deixe rodando em segundo plano — verifica a cada 2 minutos)
"""

import imaplib
import smtplib
import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr
from email.header import decode_header
import time
import os
import re
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── CONFIG ──────────────────────────────────────────────────────────────────
CONFIG = {
    "planilha_id":          "1_IVHF489S-4RiaDJYr3UVZtA2_jiSBsU5YF7mvTbFqM",
    "aba_leads":            "Leads_Email",
    "credenciais_json":     os.path.join(SCRIPT_DIR, "credentials.json"),

    # Gmail IMAP
    "imap_servidor":        "imap.gmail.com",
    "imap_porta":           993,

    # Gmail SMTP
    "smtp_servidor":        "smtp.gmail.com",
    "smtp_porta":           587,

    "email_remetente":      os.getenv("EMAIL_REMETENTE", "seuemail@gmail.com"),
    "email_senha":          os.getenv("EMAIL_SENHA", ""),
    "nome_remetente":       os.getenv("NOME_REMETENTE", "Gabriella | AXYN Automação"),
    "email_operador":       os.getenv("EMAIL_OPERADOR", os.getenv("EMAIL_REMETENTE", "")),

    # OpenAI
    "openai_api_key":       os.getenv("OPENAI_API_KEY", ""),
    "modelo_ia":            "gpt-4o",

    # Monitoramento
    "intervalo_segundos":   120,   # verifica a cada 2 minutos
}

# Mapeamento de colunas (0-based)
COL = {
    "nome":           0,
    "nicho":          1,
    "email":          2,
    "site":           3,
    "status":         5,
    "ultima_msg":     7,
    "status_ia":      12,
    "motivo_pausa":   13,
    "historico_ia":   14,
    "ultima_resp_ia": 15,
    "msg_id_enviado": 16,
}

PROMPT_SISTEMA = """\
Você é AXYN, assistente de vendas da Gabriella Pereira, especialista em automação com IA \
para pequenas e médias empresas.

SEU OBJETIVO: Qualificar leads e agendar uma reunião de 15 minutos com a Gabriella.

PRODUTO:
- Atendente virtual com IA para WhatsApp e e-mail
- Responde clientes 24h automaticamente
- Agenda serviços e consultas
- Qualifica leads antes de passar para o humano
- A partir de R$ 997 (setup) + mensalidade conforme o plano

REGRAS:
- Seja cordial, direto e profissional
- Máximo 3 parágrafos por resposta
- Nunca cite preços exatos; diga "a partir de R$ 997" se perguntado
- Se o lead demonstrar interesse real, proponha uma reunião de 15 min pelo Google Meet
- Responda SEMPRE em português brasileiro
- NÃO use asteriscos (*), hashtags (#) ou markdown — escreva texto simples para e-mail
- Assine como: Gabriella | AXYN Automação

GATILHOS DE PAUSA — responda APENAS com o JSON abaixo quando identificar:
{"PAUSE_TRIGGER": "P1", "motivo": "Lead quer fechar/comprar"}
{"PAUSE_TRIGGER": "P2", "motivo": "Pedido de desconto"}
{"PAUSE_TRIGGER": "P3", "motivo": "Tom agressivo ou hostil"}
{"PAUSE_TRIGGER": "P4", "motivo": "Serviço fora do escopo da AXYN"}
{"PAUSE_TRIGGER": "P5", "motivo": "Pediu para falar com humano"}
{"PAUSE_TRIGGER": "P6", "motivo": "Valor acima de R$ 3.000"}
{"PAUSE_TRIGGER": "P7", "motivo": "Contexto que a IA não sabe responder"}"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
log = logging.getLogger("agente_email")

# ─── GOOGLE SHEETS ────────────────────────────────────────────────────────────
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def conectar_sheets():
    creds = Credentials.from_service_account_file(CONFIG["credenciais_json"], scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(CONFIG["planilha_id"]).worksheet(CONFIG["aba_leads"])


def encontrar_lead_por_email(aba, email_lead):
    """Retorna (numero_linha, lista_linha) ou (None, None) se não encontrado."""
    dados = aba.get_all_values()
    for i, linha in enumerate(dados[1:], start=2):
        if len(linha) > COL["email"] and linha[COL["email"]].strip().lower() == email_lead.lower():
            return i, linha
    return None, None


def obter_campo(linha, col_key, default=""):
    idx = COL.get(col_key, -1)
    if idx < 0 or idx >= len(linha):
        return default
    return linha[idx].strip()


def obter_historico(linha):
    hist_raw = obter_campo(linha, "historico_ia")
    if hist_raw:
        try:
            return json.loads(hist_raw)
        except Exception:
            pass
    return []


def salvar_historico(aba, row_num, historico):
    aba.update_cell(row_num, COL["historico_ia"] + 1, json.dumps(historico, ensure_ascii=False))


def pausar_lead(aba, row_num, codigo, motivo):
    aba.update_cell(row_num, COL["status_ia"] + 1,    "PAUSADO")
    aba.update_cell(row_num, COL["motivo_pausa"] + 1, f"{codigo}: {motivo}")
    log.warning(f"Lead linha {row_num} PAUSADO — {codigo}: {motivo}")


# ─── IMAP — LEITURA DE RESPOSTAS ─────────────────────────────────────────────

def decodificar_header(valor):
    """Decodifica cabeçalhos de e-mail (suporte a UTF-8, latin-1, etc.)."""
    if not valor:
        return ""
    partes = decode_header(valor)
    resultado = []
    for parte, charset in partes:
        if isinstance(parte, bytes):
            resultado.append(parte.decode(charset or "utf-8", errors="replace"))
        else:
            resultado.append(str(parte))
    return " ".join(resultado)


def extrair_texto_plano(msg):
    """Extrai o corpo em texto puro do e-mail, ignorando HTML e anexos."""
    if msg.is_multipart():
        for parte in msg.walk():
            tipo = parte.get_content_type()
            disp = str(parte.get("Content-Disposition") or "")
            if tipo == "text/plain" and "attachment" not in disp:
                charset = parte.get_content_charset() or "utf-8"
                try:
                    return parte.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    return ""
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            return msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            return ""
    return ""


def limpar_corpo(texto):
    """Remove citações anteriores e assinaturas comuns."""
    linhas = texto.splitlines()
    limpas = []
    for linha in linhas:
        # Para na assinatura ou na citação da mensagem anterior
        if linha.startswith(">"):
            continue
        if re.match(r"^(On|Em |De:|From:|Enviado em:|Sent:|--\s*$)", linha.strip()):
            break
        limpas.append(linha)
    return "\n".join(limpas).strip()


def buscar_respostas_nao_lidas(imap):
    """Retorna lista de dicts com dados dos e-mails não lidos na caixa de entrada."""
    imap.select("INBOX")
    _, ids_bytes = imap.search(None, "UNSEEN")
    ids = ids_bytes[0].split()
    respostas = []

    for uid in ids:
        try:
            _, dados = imap.fetch(uid, "(RFC822)")
            raw = dados[0][1]
            msg = email_lib.message_from_bytes(raw)

            from_field  = decodificar_header(msg.get("From", ""))
            _, from_email = parseaddr(from_field)
            assunto     = decodificar_header(msg.get("Subject", ""))
            msg_id      = msg.get("Message-ID", "")
            in_reply_to = msg.get("In-Reply-To", "")
            corpo_raw   = extrair_texto_plano(msg)
            corpo       = limpar_corpo(corpo_raw)

            # Ignora e-mails enviados pelo próprio remetente
            if from_email.lower() == CONFIG["email_remetente"].lower():
                imap.store(uid, "+FLAGS", "\\Seen")
                continue

            # Ignora e-mails sem conteúdo relevante
            if len(corpo.strip()) < 5:
                imap.store(uid, "+FLAGS", "\\Seen")
                continue

            respostas.append({
                "from_email":  from_email.lower().strip(),
                "assunto":     assunto,
                "corpo":       corpo,
                "msg_id":      msg_id,
                "in_reply_to": in_reply_to,
            })

            # Marca como lido para não processar novamente
            imap.store(uid, "+FLAGS", "\\Seen")

        except Exception as e:
            log.error(f"Erro ao processar e-mail uid {uid}: {e}")
            continue

    return respostas


# ─── OPENAI ───────────────────────────────────────────────────────────────────

def obter_resposta_ia(historico, nome, nicho):
    """
    Chama o GPT-4o com o histórico da conversa.
    Retorna (texto_resposta, None) ou (None, dict_gatilho).
    """
    cliente = OpenAI(api_key=CONFIG["openai_api_key"])
    mensagens = [{"role": "system", "content": PROMPT_SISTEMA}]
    mensagens += historico[-20:]  # últimas 20 trocas para contexto

    try:
        resposta = cliente.chat.completions.create(
            model=CONFIG["modelo_ia"],
            messages=mensagens,
            max_tokens=500,
            temperature=0.7,
        )
        conteudo = resposta.choices[0].message.content.strip()

        # Verifica se a IA retornou um gatilho de pausa
        match = re.search(r'\{\s*"PAUSE_TRIGGER"\s*:.*?\}', conteudo, re.DOTALL)
        if match:
            try:
                gatilho = json.loads(match.group())
                return None, gatilho
            except Exception:
                pass

        return conteudo, None

    except Exception as e:
        log.error(f"Erro ao chamar OpenAI: {e}")
        return None, None


# ─── SMTP — ENVIO ─────────────────────────────────────────────────────────────

def conectar_smtp():
    servidor = smtplib.SMTP(CONFIG["smtp_servidor"], CONFIG["smtp_porta"])
    servidor.ehlo()
    servidor.starttls()
    servidor.login(CONFIG["email_remetente"], CONFIG["email_senha"])
    return servidor


def responder_email(smtp, destinatario, assunto_original, corpo_resposta, msg_id_original):
    """Envia resposta mantendo a thread (In-Reply-To + References)."""
    assunto = assunto_original if assunto_original.startswith("Re:") else f"Re: {assunto_original}"

    msg = MIMEMultipart("alternative")
    msg["From"]       = f"{CONFIG['nome_remetente']} <{CONFIG['email_remetente']}>"
    msg["To"]         = destinatario
    msg["Subject"]    = assunto
    msg["Date"]       = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="axyn.com.br")

    if msg_id_original:
        msg["In-Reply-To"] = msg_id_original
        msg["References"]  = msg_id_original

    msg.attach(MIMEText(corpo_resposta, "plain", "utf-8"))
    smtp.sendmail(CONFIG["email_remetente"], destinatario, msg.as_string())


def notificar_operador(smtp, nome_lead, email_lead, codigo, motivo):
    """Envia e-mail ao operador quando um gatilho de pausa é ativado."""
    operador = CONFIG["email_operador"] or CONFIG["email_remetente"]
    if not operador:
        return

    corpo = (
        f"AXYN — Lead precisa de atenção humana!\n\n"
        f"Lead: {nome_lead}\n"
        f"E-mail: {email_lead}\n"
        f"Código: {codigo}\n"
        f"Motivo: {motivo}\n\n"
        f"Acesse a planilha 'Leads_Email' para ver o histórico completo\n"
        f"e retomar a conversa diretamente no Gmail."
    )
    msg = MIMEMultipart()
    msg["From"]    = f"{CONFIG['nome_remetente']} <{CONFIG['email_remetente']}>"
    msg["To"]      = operador
    msg["Subject"] = f"[AXYN] Lead {nome_lead} — {codigo}: {motivo}"
    msg.attach(MIMEText(corpo, "plain", "utf-8"))

    try:
        smtp.sendmail(CONFIG["email_remetente"], operador, msg.as_string())
        log.info(f"Operador notificado: {codigo} — {nome_lead}")
    except Exception as e:
        log.error(f"Falha ao notificar operador: {e}")


# ─── CICLO DE MONITORAMENTO ───────────────────────────────────────────────────

def processar_resposta(aba, smtp, resp):
    email_lead = resp["from_email"]

    row_num, linha = encontrar_lead_por_email(aba, email_lead)
    if linha is None:
        log.info(f"  Lead não cadastrado: {email_lead} — ignorando.")
        return

    status_ia = obter_campo(linha, "status_ia") or "ATIVO"
    if status_ia not in ("ATIVO", ""):
        log.info(f"  Lead {email_lead} com status IA '{status_ia}' — ignorando.")
        return

    nome  = obter_campo(linha, "nome")  or "Lead"
    nicho = obter_campo(linha, "nicho") or "negócio"

    # Adiciona a mensagem do lead ao histórico
    historico = obter_historico(linha)
    historico.append({"role": "user", "content": resp["corpo"]})

    # Obtém resposta da IA
    texto_ia, gatilho = obter_resposta_ia(historico, nome, nicho)

    if gatilho:
        codigo = gatilho.get("PAUSE_TRIGGER", "P7")
        motivo = gatilho.get("motivo", "Gatilho detectado")
        pausar_lead(aba, row_num, codigo, motivo)
        salvar_historico(aba, row_num, historico)
        notificar_operador(smtp, nome, email_lead, codigo, motivo)
        return

    if not texto_ia:
        log.warning(f"  IA não retornou resposta para {email_lead}.")
        return

    # Envia a resposta
    try:
        responder_email(smtp, email_lead, resp["assunto"], texto_ia, resp["msg_id"])
        log.info(f"  Respondido: {email_lead}")
    except Exception as e:
        log.error(f"  Erro ao enviar resposta para {email_lead}: {e}")
        return

    # Persiste histórico atualizado
    historico.append({"role": "assistant", "content": texto_ia})
    salvar_historico(aba, row_num, historico)
    aba.update_cell(row_num, COL["status"] + 1,         "Em conversa")
    aba.update_cell(row_num, COL["ultima_resp_ia"] + 1,
                    datetime.now().strftime("%d/%m/%Y %H:%M"))


def ciclo(aba):
    imap = None
    smtp = None
    try:
        imap = imaplib.IMAP4_SSL(CONFIG["imap_servidor"], CONFIG["imap_porta"])
        imap.login(CONFIG["email_remetente"], CONFIG["email_senha"])

        respostas = buscar_respostas_nao_lidas(imap)
        if not respostas:
            return

        log.info(f"{len(respostas)} nova(s) resposta(s) recebida(s).")

        smtp = conectar_smtp()
        for resp in respostas:
            log.info(f"Processando: {resp['from_email']}")
            processar_resposta(aba, smtp, resp)

    except imaplib.IMAP4.error as e:
        log.error(f"Erro IMAP: {e}")
    except smtplib.SMTPException as e:
        log.error(f"Erro SMTP: {e}")
    except Exception as e:
        log.error(f"Erro inesperado no ciclo: {e}")
    finally:
        if smtp:
            try:
                smtp.quit()
            except Exception:
                pass
        if imap:
            try:
                imap.logout()
            except Exception:
                pass


# ─── PRINCIPAL ────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("  AXYN — Agente IA de E-mail iniciado")
    log.info("=" * 55)

    if not CONFIG["openai_api_key"]:
        log.error("OPENAI_API_KEY não definida. Encerrando.")
        return
    if not CONFIG["email_senha"]:
        log.error("EMAIL_SENHA não definida. Encerrando.")
        return

    log.info("Conectando ao Google Sheets...")
    aba = conectar_sheets()
    log.info(f"Monitorando caixa a cada {CONFIG['intervalo_segundos']}s. Ctrl+C para parar.")

    while True:
        try:
            ciclo(aba)
        except KeyboardInterrupt:
            log.info("Agente encerrado pelo operador.")
            break
        except Exception as e:
            log.error(f"Erro no loop principal: {e}")

        time.sleep(CONFIG["intervalo_segundos"])


if __name__ == "__main__":
    main()
