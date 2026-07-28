import json
from django import template

register = template.Library()


@register.filter
def format_ia_value(valor):
    """
    Formata valores do JSON da IA para exibição legível no template.
    - Listas de dicts (pisos, beneficios) → lista HTML formatada
    - Listas simples → lista com bullets
    - Dicts → chave: valor
    - Strings longas → parágrafos
    - None → -
    """
    if valor is None:
        return '<span class="text-muted">-</span>'

    if isinstance(valor, bool):
        return "Sim" if valor else "Não"

    if isinstance(valor, (int, float)):
        return str(valor)

    if isinstance(valor, list):
        if not valor:
            return '<span class="text-muted">-</span>'

        html = '<ul class="list-unstyled mb-0">'
        for item in valor:
            if isinstance(item, dict):
                # Formata dict como linhas com chave em negrito
                html += '<li class="mb-2">'
                for k, v in item.items():
                    html += f'<div><strong>{k.replace("_", " ").title()}:</strong> {format_ia_value(v)}</div>'
                html += '</li>'
            elif isinstance(item, list):
                html += f'<li>{format_ia_value(item)}</li>'
            else:
                html += f'<li>{item}</li>'
        html += '</ul>'
        return html

    if isinstance(valor, dict):
        if not valor:
            return '<span class="text-muted">-</span>'
        html = '<ul class="list-unstyled mb-0">'
        for k, v in valor.items():
            html += f'<li><strong>{k.replace("_", " ").title()}:</strong> {format_ia_value(v)}</li>'
        html += '</ul>'
        return html

    # String
    s = str(valor)
    if len(s) > 200:
        return f'<pre class="mb-0" style="white-space: pre-wrap;">{s}</pre>'
    return s
