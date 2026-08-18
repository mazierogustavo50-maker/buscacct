import os
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.core.mail import send_mail, EmailMessage
from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings

from cctcore.models import DocumentoCCT, ConfiguracaoSistema, NotificacaoDocumentoCCT
from cctbuscador.models import ExecucaoScraper


class Command(BaseCommand):
    help = "Envia e-mails de notificação de novas CCTs para clientes (empresas) e escritório."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simula sem enviar e-mails.")
        parser.add_argument("--apenas-empresas", action="store_true", help="Só envia para empresas.")
        parser.add_argument("--apenas-escritorio", action="store_true", help="Só envia para e-mails internos.")
        parser.add_argument("--dias", type=int, default=1, help="Considera CCTs dos últimos N dias.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        apenas_empresas = options["apenas_empresas"]
        apenas_escritorio = options["apenas_escritorio"]
        dias = options["dias"]

        config = ConfiguracaoSistema.get_config()
        emails_internos = config.emails_internos_lista()
        desde = timezone.now() - timedelta(days=dias)

        # CCTs novas/extraídas recentemente
        docs = DocumentoCCT.objects.filter(
            ativo=True,
            data_registro_mte__gte=desde,
            status_extracao=DocumentoCCT.STATUS_EXTRAIDO,
        ).select_related("sindicato").order_by("-data_registro_mte")

        if not docs.exists():
            self.stdout.write(self.style.NOTICE("Nenhuma CCT nova nos últimos %d dias." % dias))
            return

        total_enviados = 0
        total_erros = 0

        # ========== ENVIO PARA EMPRESAS ==========
        if not apenas_escritorio:
            for doc in docs:
                empresas = doc.sindicato.empresas.filter(empresa__email__isnull=False).exclude(empresa__email="").select_related("empresa")
                for rel in empresas:
                    empresa = rel.empresa
                    email = empresa.email.strip().lower()
                    if not email:
                        continue
                    # Evita duplicado
                    notif, criada = NotificacaoDocumentoCCT.objects.get_or_create(
                        documento=doc, destinatario=email,
                        defaults={"status": NotificacaoDocumentoCCT.STATUS_PENDENTE}
                    )
                    if not criada and notif.status == NotificacaoDocumentoCCT.STATUS_ENVIADA:
                        continue

                    assunto = f"Nova CCT disponível — {doc.sindicato.codigo}"
                    corpo = render_to_string("emails/nova_cct_empresa.html", {
                        "documento": doc,
                        "empresa": empresa,
                        "data_envio": timezone.now().strftime("%d/%m/%Y %H:%M"),
                    })
                    try:
                        if not dry_run:
                            msg = EmailMessage(
                                subject=assunto,
                                body=corpo,
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                to=[email],
                            )
                            msg.content_subtype = "html"
                            msg.send()
                            notif.status = NotificacaoDocumentoCCT.STATUS_ENVIADA
                            notif.enviada_em = timezone.now()
                            notif.save(update_fields=["status", "enviada_em"])
                        self.stdout.write(self.style.SUCCESS(f"  {'[DRY-RUN] ' if dry_run else ''}Empresa {empresa.codigo} <{email}> — CCT {doc.pk}"))
                        total_enviados += 1
                    except Exception as e:
                        notif.tentativas += 1
                        notif.ultimo_erro = str(e)
                        notif.status = NotificacaoDocumentoCCT.STATUS_ERRO
                        notif.save(update_fields=["tentativas", "ultimo_erro", "status"])
                        self.stdout.write(self.style.ERROR(f"  ERRO {empresa.codigo} <{email}>: {e}"))
                        total_erros += 1

        # ========== ENVIO PARA ESCRITÓRIO ==========
        if not apenas_empresas and emails_internos:
            for doc in docs:
                for email in emails_internos:
                    notif, criada = NotificacaoDocumentoCCT.objects.get_or_create(
                        documento=doc, destinatario=email,
                        defaults={"status": NotificacaoDocumentoCCT.STATUS_PENDENTE}
                    )
                    if not criada and notif.status == NotificacaoDocumentoCCT.STATUS_ENVIADA:
                        continue

                    assunto = f"[Escritório] Nova CCT extraída — {doc.sindicato.codigo}"
                    corpo = render_to_string("emails/nova_cct_escritorio.html", {
                        "documento": doc,
                        "data_envio": timezone.now().strftime("%d/%m/%Y %H:%M"),
                    })
                    try:
                        if not dry_run:
                            msg = EmailMessage(
                                subject=assunto,
                                body=corpo,
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                to=[email],
                            )
                            msg.content_subtype = "html"
                            msg.send()
                            notif.status = NotificacaoDocumentoCCT.STATUS_ENVIADA
                            notif.enviada_em = timezone.now()
                            notif.save(update_fields=["status", "enviada_em"])
                        self.stdout.write(self.style.SUCCESS(f"  {'[DRY-RUN] ' if dry_run else ''}Escritório <{email}> — CCT {doc.pk}"))
                        total_enviados += 1
                    except Exception as e:
                        notif.tentativas += 1
                        notif.ultimo_erro = str(e)
                        notif.status = NotificacaoDocumentoCCT.STATUS_ERRO
                        notif.save(update_fields=["tentativas", "ultimo_erro", "status"])
                        self.stdout.write(self.style.ERROR(f"  ERRO escritório <{email}>: {e}"))
                        total_erros += 1

        self.stdout.write(self.style.NOTICE(f"\nResumo: {total_enviados} enviado(s), {total_erros} erro(s)."))
