"""
AXYN Prospector — Agendador
============================
Execute este arquivo para rodar toda a automação.
Pode ser acionado manualmente ou via crontab/Agendador de Tarefas.

FLUXOS DISPONÍVEIS:
  whatsapp  → Coleta Maps + Dispara WhatsApp  (padrão)
  email     → Coleta e-mails + Dispara e-mails
  tudo      → Ambos os fluxos em sequência

EXECUÇÃO MANUAL:
  python 0_rodar_tudo.py                   # WhatsApp (padrão)
  python 0_rodar_tudo.py --fluxo email     # apenas e-mail
  python 0_rodar_tudo.py --fluxo tudo      # ambos
  python 0_rodar_tudo.py --so-disparar     # pula coleta de leads (WhatsApp)

COM CRONTAB (Linux/Mac) — roda às 9h e 14h de segunda a sexta:
  0 9,14 * * 1-5 cd /caminho/para/scripts && python 0_rodar_tudo.py >> /tmp/axyn.log 2>&1
  0 9,14 * * 1-5 cd /caminho/para/scripts && python 0_rodar_tudo.py --fluxo email >> /tmp/axyn_email.log 2>&1

NOTA: O agente IA (scripts 3 e 6) deve ficar rodando separadamente em segundo plano:
  python scripts/3_agente_ia.py
  python scripts/6_agente_email_ia.py
"""

import subprocess
import sys
import argparse
from datetime import datetime


def log(msg):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    print(f"[{agora}] {msg}", flush=True)


def rodar_script(nome):
    log(f"Iniciando: {nome}")
    result = subprocess.run(
        [sys.executable, nome],
        capture_output=False,
        text=True,
    )
    if result.returncode == 0:
        log(f"✅ Concluído: {nome}")
    else:
        log(f"❌ Erro em: {nome} (código {result.returncode})")
    return result.returncode == 0


def fluxo_whatsapp(so_disparar):
    if not so_disparar:
        log("Etapa 1/2 — WhatsApp: Coletando leads do Google Maps...")
        rodar_script("1_coletar_leads.py")
    else:
        log("Etapa 1/2 — WhatsApp: Coleta ignorada (--so-disparar).")
    log("Etapa 2/2 — WhatsApp: Disparando mensagens...")
    rodar_script("2_disparar_whatsapp.py")


def fluxo_email(so_disparar):
    if not so_disparar:
        log("Etapa 1/2 — E-mail: Coletando e-mails na internet...")
        rodar_script("4_coletar_emails.py")
    else:
        log("Etapa 1/2 — E-mail: Coleta ignorada (--so-disparar).")
    log("Etapa 2/2 — E-mail: Disparando e-mails...")
    rodar_script("5_disparar_emails.py")


def main():
    parser = argparse.ArgumentParser(description="AXYN Prospector — Rotina Automática")
    parser.add_argument(
        "--fluxo",
        choices=["whatsapp", "email", "tudo"],
        default="whatsapp",
        help="Fluxo a executar: 'whatsapp' (padrão), 'email' ou 'tudo'",
    )
    parser.add_argument(
        "--so-disparar",
        action="store_true",
        help="Pula a coleta de leads e vai direto para o disparo",
    )
    args = parser.parse_args()

    print("=" * 55)
    print("  AXYN Prospector — Rotina Automática")
    print(f"  {datetime.now().strftime('%d/%m/%Y às %H:%M')}  |  Fluxo: {args.fluxo}")
    print("=" * 55)

    if args.fluxo in ("whatsapp", "tudo"):
        fluxo_whatsapp(args.so_disparar)

    if args.fluxo in ("email", "tudo"):
        fluxo_email(args.so_disparar)

    log("Rotina concluída.")


if __name__ == "__main__":
    main()
