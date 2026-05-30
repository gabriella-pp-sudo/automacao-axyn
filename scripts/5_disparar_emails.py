"""
AXYN Prospector — Script 5: Disparo de E-mails
================================================
Lê os leads da aba 'Leads_Email' e envia e-mails personalizados
de prospecção em cadência automática (mensagem inicial + 3 follow-ups).

PRÉ-REQUISITOS:
  1. Ative a verificação em 2 etapas na sua conta Gmail
  2. Crie uma "Senha de App" em: myaccount.google.com/apppasswords
  3. Defina as variáveis de ambiente antes de executar:

     Windows PowerShell:
       $env:EMAIL_REMETENTE = "seuemail@gmail.com"
       $env:EMAIL_SENHA      = "xxxx xxxx xxxx xxxx"   (senha de app)
       $env:NOME_REMETENTE   = "Gabriella | AXYN"      (opcional)

     Linux/Mac:
       export EMAIL_REMETENTE="seuemail@gmail.com"
       export EMAIL_SENHA="xxxx xxxx xxxx xxxx"

  4. Execute: python scripts/5_disparar_emails.py

CADÊNCIA:
  Dia 0  → Mensagem inicial
  Dia 3  → Follow-up 1
  Dia 7  → Follow-up 2
  Dia 14 → Follow-up 3 (última mensagem)
"""

import smtplib
import time
import os
import gspread
from google.oauth2.service_account import Credentials
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── CONFIG ──────────────────────────────────────────────────────────────────
CONFIG = {
    "planilha_id":       "1_IVHF489S-4RiaDJYr3UVZtA2_jiSBsU5YF7mvTbFqM",
    "aba_leads":         "Leads_Email",
    "credenciais_json":  os.path.join(SCRIPT_DIR, "credentials.json"),

    # SMTP — Gmail
    "smtp_servidor":     "smtp.gmail.com",
    "smtp_porta":        587,
    "email_remetente":   os.getenv("EMAIL_REMETENTE", "seuemail@gmail.com"),
    "email_senha":       os.getenv("EMAIL_SENHA", ""),
    "nome_remetente":    os.getenv("NOME_REMETENTE", "Gabriella | AXYN Automação"),

    # Cadência de follow-ups (em dias desde o envio anterior)
    "dias_followup1":    3,
    "dias_followup2":    7,
    "dias_followup3":    14,

    # Limites de segurança
    "max_emails_rodada": 50,    # Gmail recomendado: 50/rodada no início (warming)
    "pausa_entre_envios": 30,   # segundos entre cada envio

    # Horário comercial
    "hora_inicio":       8,
    "hora_fim":          18,
}

# Mapeamento de colunas (0-based para listas, +1 para update_cell)
COL = {
    "nome":           0,
    "nicho":          1,
    "email":          2,
    "site":           3,
    "status":         5,
    "ultima_msg":     7,
    "followup1":      8,
    "followup2":      9,
    "followup3":      10,
    "status_ia":      12,
    "msg_id_enviado": 16,
}

# ─── TEMPLATES DE E-MAIL ──────────────────────────────────────────────────────

def template_inicial(nome_empresa, nicho):
    primeiro_nome = nome_empresa.split()[0] if nome_empresa else "Olá"
    assunto = f"Pergunta rápida sobre o {primeiro_nome}"
    html = f"""\
<html>
<body style="font-family:Arial,sans-serif;color:#333;max-width:580px;margin:0 auto;padding:24px;line-height:1.6">
<p>Oi! Tudo bem?</p>

<p>Me chamo <strong>Gabriella</strong> e sou especialista em automação com IA aqui em Ribeirão.</p>

<p>Pergunta rápida: quantas mensagens e ligações o <strong>{nome_empresa}</strong> recebe por dia
que ficam sem resposta fora do horário comercial?</p>

<p>Pergunto porque a maioria dos <strong>{nicho}s</strong> que converso perde de 30% a 50% dos
novos clientes exatamente aí — quando o estabelecimento está fechado ou a equipe está ocupada.</p>

<p>A AXYN resolve isso com um <strong>atendente virtual com IA</strong> que:</p>
<ul>
  <li>✅ Responde clientes 24h no WhatsApp e por e-mail</li>
  <li>✅ Agenda consultas e serviços automaticamente</li>
  <li>✅ Qualifica leads e só te chama quando o cliente está pronto para fechar</li>
  <li>✅ Tudo personalizado com a voz e identidade do seu negócio</li>
</ul>

<p>Vale uma conversa rápida de 15 minutos para ver se faz sentido pro <strong>{nome_empresa}</strong>?</p>

<p>É só responder este e-mail ou me chamar no WhatsApp.</p>

<p>Abraços,<br>
<strong>Gabriella Pereira</strong><br>
AXYN Automação com IA<br>
<a href="https://wa.me/5516999999999">📱 (16) 99999-9999</a></p>

<hr style="border:none;border-top:1px solid #eee;margin-top:32px">
<p style="font-size:11px;color:#aaa">
Você recebeu este e-mail porque o <strong>{nome_empresa}</strong> foi identificado como
potencial cliente dos nossos serviços.
Para não receber mais mensagens,
<a href="mailto:{CONFIG['email_remetente']}?subject=Descadastrar%20{nome_empresa}" style="color:#aaa">clique aqui</a>.
</p>
</body>
</html>"""

    texto = f"""\
Oi! Tudo bem?

Me chamo Gabriella e sou especialista em automação com IA aqui em Ribeirão.

Pergunta rápida: quantas mensagens e ligações o {nome_empresa} recebe por dia que ficam \
sem resposta fora do horário comercial?

Pergunto porque a maioria dos {nicho}s que converso perde de 30% a 50% dos novos clientes \
exatamente aí — quando o estabelecimento está fechado ou a equipe está ocupada.

A AXYN resolve isso com um atendente virtual com IA que:
✅ Responde clientes 24h no WhatsApp e por e-mail
✅ Agenda consultas e serviços automaticamente
✅ Qualifica leads e só te chama quando o cliente está pronto para fechar
✅ Tudo personalizado com a voz e identidade do seu negócio

Vale uma conversa rápida de 15 minutos para ver se faz sentido pro {nome_empresa}?

É só responder este e-mail ou me chamar no WhatsApp.

Abraços,
Gabriella Pereira
AXYN Automação com IA
📱 (16) 99999-9999"""
    return assunto, html, texto


def template_followup1(nome_empresa, nicho):
    primeiro_nome = nome_empresa.split()[0] if nome_empresa else "Olá"
    assunto = f"Re: Pergunta rápida sobre o {primeiro_nome}"
    html = f"""\
<html>
<body style="font-family:Arial,sans-serif;color:#333;max-width:580px;margin:0 auto;padding:24px;line-height:1.6">
<p>Oi {primeiro_nome}, tudo bem?</p>

<p>Enviei uma mensagem alguns dias atrás e queria saber se chegou bem.</p>

<p>Em resumo: desenvolvemos um <strong>atendente virtual com IA</strong> para {nicho}s que
responde clientes automaticamente no WhatsApp e por e-mail, 24h por dia — sem contratar mais funcionários.</p>

<p>Seria interessante conversar 15 minutinhos sobre isso?</p>

<p>Abraços,<br>
<strong>Gabriella</strong> | AXYN Automação</p>
</body>
</html>"""

    texto = f"""\
Oi {primeiro_nome}, tudo bem?

Enviei uma mensagem alguns dias atrás e queria saber se chegou bem.

Em resumo: desenvolvemos um atendente virtual com IA para {nicho}s que responde clientes \
automaticamente no WhatsApp e por e-mail, 24h por dia — sem contratar mais funcionários.

Seria interessante conversar 15 minutinhos sobre isso?

Abraços,
Gabriella | AXYN Automação"""
    return assunto, html, texto


def template_followup2(nome_empresa, nicho):
    primeiro_nome = nome_empresa.split()[0] if nome_empresa else "Olá"
    assunto = f"{primeiro_nome}, isso faz sentido para o seu {nicho}?"
    html = f"""\
<html>
<body style="font-family:Arial,sans-serif;color:#333;max-width:580px;margin:0 auto;padding:24px;line-height:1.6">
<p>Oi {primeiro_nome},</p>

<p>Vou ser direta: <strong>{nicho}s perdem clientes todo dia</strong> porque não conseguem
responder rápido o suficiente.</p>

<p>O problema não é falta de vontade — é que você está ocupado <em>atendendo quem já está lá</em>
enquanto novos clientes mandam mensagem e, sem resposta, vão para o concorrente.</p>

<p>A nossa solução custa menos de <strong>R$ 150/mês</strong> e já se paga se você fechar
<strong>1 cliente extra por mês</strong> graças ao atendimento automático.</p>

<p>Posso te mandar um caso real de um {nicho} aqui da região que implementou e o resultado?</p>

<p>Abraços,<br>
<strong>Gabriella</strong> | AXYN Automação</p>
</body>
</html>"""

    texto = f"""\
Oi {primeiro_nome},

Vou ser direta: {nicho}s perdem clientes todo dia porque não conseguem responder rápido o suficiente.

O problema não é falta de vontade — é que você está ocupado atendendo quem já está lá enquanto \
novos clientes mandam mensagem e, sem resposta, vão para o concorrente.

A nossa solução custa menos de R$ 150/mês e já se paga se você fechar 1 cliente extra por mês \
graças ao atendimento automático.

Posso te mandar um caso real de um {nicho} aqui da região que implementou e o resultado?

Abraços,
Gabriella | AXYN Automação"""
    return assunto, html, texto


def template_followup3(nome_empresa, nicho):
    primeiro_nome = nome_empresa.split()[0] if nome_empresa else "Olá"
    assunto = f"Última mensagem, {primeiro_nome}"
    html = f"""\
<html>
<body style="font-family:Arial,sans-serif;color:#333;max-width:580px;margin:0 auto;padding:24px;line-height:1.6">
<p>Oi {primeiro_nome},</p>

<p>Prometo que esta é minha última mensagem. 😊</p>

<p>Tentei falar sobre como o <strong>{nome_empresa}</strong> poderia atender mais clientes
automaticamente com IA, mas entendo que talvez não seja o momento certo.</p>

<p>Se um dia fizer sentido revisar isso — especialmente se você estiver perdendo clientes
por demora no atendimento — estarei por aqui.</p>

<p>Abraços e muito sucesso,<br>
<strong>Gabriella</strong> | AXYN Automação</p>
</body>
</html>"""

    texto = f"""\
Oi {primeiro_nome},

Prometo que esta é minha última mensagem. :)

Tentei falar sobre como o {nome_empresa} poderia atender mais clientes automaticamente com IA, \
mas entendo que talvez não seja o momento certo.

Se um dia fizer sentido revisar isso — especialmente se você estiver perdendo clientes por demora \
no atendimento — estarei por aqui.

Abraços e muito sucesso,
Gabriella | AXYN Automação"""
    return assunto, html, texto


TEMPLATES = {
    "inicial":   template_inicial,
    "followup1": template_followup1,
    "followup2": template_followup2,
    "followup3": template_followup3,
}

STATUS_APOS_ENVIO = {
    "inicial":   "Email enviado",
    "followup1": "Follow-up 1",
    "followup2": "Follow-up 2",
    "followup3": "Follow-up 3",
}

# ─── GOOGLE SHEETS ────────────────────────────────────────────────────────────
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def conectar_sheets():
    creds = Credentials.from_service_account_file(CONFIG["credenciais_json"], scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(CONFIG["planilha_id"]).worksheet(CONFIG["aba_leads"])


def parse_data(texto):
    if not texto:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto.strip(), fmt)
        except ValueError:
            continue
    return None


def dias_desde(texto):
    dt = parse_data(texto)
    if not dt:
        return 9999
    return (datetime.now() - dt).days


def obter_campo(linha, col_key, default=""):
    idx = COL.get(col_key, -1)
    if idx < 0 or idx >= len(linha):
        return default
    return linha[idx].strip()


# ─── LÓGICA DE DISPARO ────────────────────────────────────────────────────────

def horario_permitido():
    hora = datetime.now().hour
    return CONFIG["hora_inicio"] <= hora < CONFIG["hora_fim"]


def tipo_para_enviar(linha):
    """Determina qual tipo de e-mail deve ser enviado agora, ou None."""
    status    = obter_campo(linha, "status")
    status_ia = obter_campo(linha, "status_ia") or "ATIVO"

    if status_ia not in ("ATIVO", ""):
        return None  # Pausado, fechado ou perdido

    if status == "Prospectado":
        return "inicial"

    if status == "Email enviado":
        if dias_desde(obter_campo(linha, "ultima_msg")) >= CONFIG["dias_followup1"]:
            return "followup1"

    if status == "Follow-up 1":
        if dias_desde(obter_campo(linha, "followup1")) >= CONFIG["dias_followup2"]:
            return "followup2"

    if status == "Follow-up 2":
        if dias_desde(obter_campo(linha, "followup2")) >= CONFIG["dias_followup3"]:
            return "followup3"

    return None


# ─── ENVIO ────────────────────────────────────────────────────────────────────

def conectar_smtp():
    servidor = smtplib.SMTP(CONFIG["smtp_servidor"], CONFIG["smtp_porta"])
    servidor.ehlo()
    servidor.starttls()
    servidor.login(CONFIG["email_remetente"], CONFIG["email_senha"])
    return servidor


def montar_email(destinatario, nome_empresa, nicho, tipo, msg_id_anterior=None):
    """Monta o objeto MIMEMultipart pronto para envio."""
    assunto, html, texto = TEMPLATES[tipo](nome_empresa, nicho)

    msg = MIMEMultipart("alternative")
    msg["From"]       = f"{CONFIG['nome_remetente']} <{CONFIG['email_remetente']}>"
    msg["To"]         = destinatario
    msg["Subject"]    = assunto
    msg["Date"]       = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="axyn.com.br")

    # Encadeia como reply para follow-ups manterem a thread
    if msg_id_anterior and tipo != "inicial":
        msg["In-Reply-To"] = msg_id_anterior
        msg["References"]  = msg_id_anterior

    msg.attach(MIMEText(texto, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))
    return msg


def enviar_email(servidor, destinatario, nome_empresa, nicho, tipo, msg_id_anterior=None):
    """Envia o e-mail e retorna o Message-ID gerado."""
    msg = montar_email(destinatario, nome_empresa, nicho, tipo, msg_id_anterior)
    servidor.sendmail(CONFIG["email_remetente"], destinatario, msg.as_string())
    return msg["Message-ID"]


# ─── PRINCIPAL ────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  AXYN Prospector — Disparo de E-mails")
    print("=" * 55)

    if not horario_permitido():
        print(f"\n⏰  Fora do horário comercial ({CONFIG['hora_inicio']}h–{CONFIG['hora_fim']}h). Encerrando.")
        return

    if not CONFIG["email_senha"]:
        print("\n❌  EMAIL_SENHA não definida. Configure a variável de ambiente e tente novamente.")
        return

    print("\n📋 Conectando ao Google Sheets...")
    aba = conectar_sheets()
    dados = aba.get_all_values()
    leads = dados[1:] if len(dados) > 1 else []
    print(f"   {len(leads)} lead(s) encontrado(s) na planilha.")

    print("\n📧 Conectando ao servidor SMTP...")
    try:
        servidor = conectar_smtp()
        print("   Conexão SMTP estabelecida.")
    except Exception as e:
        print(f"❌  Falha ao conectar ao SMTP: {e}")
        return

    enviados = 0

    for i, linha in enumerate(leads, start=2):  # linha 2 = segunda linha da planilha
        if enviados >= CONFIG["max_emails_rodada"]:
            print(f"\n🛑  Limite de {CONFIG['max_emails_rodada']} e-mails atingido para esta rodada.")
            break

        email      = obter_campo(linha, "email")
        nome       = obter_campo(linha, "nome") or "Empresa"
        nicho      = obter_campo(linha, "nicho") or "negócio"
        msg_id_ant = obter_campo(linha, "msg_id_enviado")

        if not email or "@" not in email:
            continue

        tipo = tipo_para_enviar(linha)
        if not tipo:
            continue

        try:
            print(f"\n  📤 Enviando '{tipo}' para {nome} <{email}>...")
            msg_id = enviar_email(servidor, email, nome, nicho, tipo, msg_id_ant or None)
            agora = datetime.now().strftime("%d/%m/%Y %H:%M")

            # Atualiza status e timestamps na planilha
            aba.update_cell(i, COL["status"] + 1,    STATUS_APOS_ENVIO[tipo])
            aba.update_cell(i, COL["ultima_msg"] + 1, agora)

            if tipo == "followup1":
                aba.update_cell(i, COL["followup1"] + 1, agora)
            elif tipo == "followup2":
                aba.update_cell(i, COL["followup2"] + 1, agora)
            elif tipo == "followup3":
                aba.update_cell(i, COL["followup3"] + 1, agora)
            elif tipo == "inicial":
                aba.update_cell(i, COL["msg_id_enviado"] + 1, msg_id)

            enviados += 1
            print(f"      ✅ Enviado! ({enviados}/{CONFIG['max_emails_rodada']})")

            # Atualiza a linha local para não reprocessar nesta rodada
            if COL["status"] < len(linha):
                linha[COL["status"]] = STATUS_APOS_ENVIO[tipo]

            time.sleep(CONFIG["pausa_entre_envios"])

        except smtplib.SMTPRecipientsRefused:
            print(f"      ❌ E-mail rejeitado pelo servidor: {email}")
            aba.update_cell(i, COL["status"] + 1, "Email inválido")
        except smtplib.SMTPServerDisconnected:
            print("      ⚠️  Conexão SMTP perdida. Reconectando...")
            try:
                servidor = conectar_smtp()
            except Exception:
                print("      ❌ Falha ao reconectar. Encerrando.")
                break
        except Exception as e:
            print(f"      ⚠️  Erro inesperado: {e}")

    try:
        servidor.quit()
    except Exception:
        pass

    print(f"\n{'=' * 55}")
    print(f"  ✅ Disparo concluído. {enviados} e-mail(s) enviado(s).")
    print("=" * 55)


if __name__ == "__main__":
    main()
