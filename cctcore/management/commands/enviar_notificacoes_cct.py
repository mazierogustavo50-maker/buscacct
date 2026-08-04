from django.core.management.base import BaseCommand
from django.utils import timezone

from cctcore.models import NotificacaoDocumentoCCT
from cctcore.notifications import enviar_notificacao


class Command(BaseCommand):
    help = "Envia avisos pendentes de novas convenções coletivas."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=100)

    def handle(self, *args, **options):
        enviadas = 0
        pendentes = NotificacaoDocumentoCCT.objects.filter(
            status__in=[NotificacaoDocumentoCCT.STATUS_PENDENTE, NotificacaoDocumentoCCT.STATUS_ERRO]
        ).select_related("documento__sindicato").order_by("criada_em")[:options["limite"]]
        for item in pendentes:
            item.tentativas += 1
            item.save(update_fields=["tentativas"])
            try:
                enviar_notificacao(item)
            except Exception as exc:
                item.status = NotificacaoDocumentoCCT.STATUS_ERRO
                item.ultimo_erro = str(exc)
                item.save(update_fields=["status", "ultimo_erro"])
                self.stderr.write(f"Falha para {item.destinatario}: {exc}")
                continue
            item.status = NotificacaoDocumentoCCT.STATUS_ENVIADA
            item.enviada_em = timezone.now()
            item.ultimo_erro = ""
            item.save(update_fields=["status", "enviada_em", "ultimo_erro"])
            enviadas += 1
        self.stdout.write(self.style.SUCCESS(f"{enviadas} notificação(ões) enviada(s)."))
