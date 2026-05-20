# AXYN Prospector

Automação completa de prospecção de clientes via Google Maps + WhatsApp Web + Google Sheets.

## O que faz

1. **Coleta leads** — busca negócios sem site no Google Maps por nicho e cidade
2. **Dispara mensagens** — envia mensagens personalizadas via WhatsApp Web (gratuito, sem API paga)
3. **Follow-ups automáticos** — sequência de 3 follow-ups ao longo de 7 dias
4. **CRM visual** — dashboard em `crm/index.html` para acompanhar os leads

## Início rápido

```bash
# 1. Instale as dependências
pip install -r requirements.txt

# 2. Configure o ID da planilha e as credenciais
# Veja: docs/CONFIGURACAO.md

# 3. Colete leads
python scripts/1_coletar_leads.py

# 4. Dispare mensagens
python scripts/2_disparar_whatsapp.py

# 5. Ou rode tudo de uma vez
python scripts/0_rodar_tudo.py
```

## Documentação completa

Veja [docs/CONFIGURACAO.md](docs/CONFIGURACAO.md) para o guia detalhado de configuração.

## Requisitos

- Python 3.9+
- Google Chrome
- Conta Google com Google Sheets e Google Drive API habilitados
- Número de WhatsApp (preferencialmente Business)

## Segurança

- `credentials.json` e a pasta `whatsapp_session/` estão no `.gitignore` — nunca são enviados ao repositório
- O script de disparo verifica o horário antes de enviar (8h-18h)
- Limite configurável de mensagens por rodada
