from django.core.mail import send_mail
from django.conf import settings
from .models import ConfiguracaoSistema, Empresa, NotificacaoDocumentoCCT


def destinatarios_do_documento(documento):
    config = ConfiguracaoSistema.get_config()
    emails = set(config.emails_internos_lista())
    emails.update(
        Empresa.objects.filter(sindicatos__sindicato=documento.sindicato, ativo=True)
        .exclude(email="").values_list("email", flat=True)
    )
    return sorted({e.strip().lower() for e in emails if e and e.strip()})


def enfileirar_notificacoes(documento):
    for email in destinatarios_do_documento(documento):
        NotificacaoDocumentoCCT.objects.get_or_create(documento=documento, destinatario=email)


def enviar_notificacao(notificacao):
    documento = notificacao.documento
    assunto = f"Nova {documento.tipo} disponível - {documento.sindicato.nome}"
    corpo = (
        "Uma nova convenção coletiva foi identificada pelo sistema.\n\n"
        f"Sindicato: {documento.sindicato.nome}\n"
        f"Tipo: {documento.tipo}\n"
        f"Vigência: {documento.data_inicio_vigencia or 'não informada'} a {documento.data_fim_vigencia or 'não informada'}\n"
        f"Arquivo: {documento.arquivo_pdf}\n"
    )
    send_mail(assunto, corpo, settings.DEFAULT_FROM_EMAIL, [notificacao.destinatario], fail_silently=False)
