from django import forms
from cctcore.models import Sindicato, Empresa, EmpresaSindicato, EmpresaDocumentoCCT, DocumentoCCT


class SindicatoForm(forms.ModelForm):
    class Meta:
        model = Sindicato
        fields = ["codigo", "nome", "cnpj"]
        widgets = {
            "codigo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Código do sindicato"}),
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome do sindicato"}),
            "cnpj": forms.TextInput(attrs={"class": "form-control", "placeholder": "CNPJ (somente números)"}),
        }
        labels = {
            "codigo": "Código",
            "nome": "Nome do Sindicato",
            "cnpj": "CNPJ",
        }


class EmpresaForm(forms.ModelForm):
    sindicatos = forms.ModelMultipleChoiceField(
        queryset=Sindicato.objects.order_by("nome"),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
        label="Sindicatos vinculados",
    )
    documentos_cct = forms.ModelMultipleChoiceField(
        queryset=DocumentoCCT.objects.filter(ativo=True).select_related("sindicato").order_by("-data_inicio_vigencia"),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
        label="Convenções Coletivas (CCT) vinculadas",
    )

    class Meta:
        model = Empresa
        fields = ["codigo", "nome"]
        widgets = {
            "codigo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Código da empresa"}),
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome da empresa"}),
        }
        labels = {
            "codigo": "Código",
            "nome": "Nome da Empresa",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["sindicatos"].initial = Sindicato.objects.filter(
                empresas__empresa=self.instance
            ).values_list("pk", flat=True)
            self.fields["documentos_cct"].initial = DocumentoCCT.objects.filter(
                empresas_vinculadas__empresa=self.instance
            ).values_list("pk", flat=True)

    def save(self, commit=True):
        empresa = super().save(commit=commit)
        if commit:
            sindicatos = self.cleaned_data.get("sindicatos", [])
            # Sincroniza vínculos sindicatos
            EmpresaSindicato.objects.filter(empresa=empresa).delete()
            for sindicato in sindicatos:
                EmpresaSindicato.objects.get_or_create(empresa=empresa, sindicato=sindicato)

            documentos = self.cleaned_data.get("documentos_cct", [])
            # Sincroniza vínculos documentos CCT
            EmpresaDocumentoCCT.objects.filter(empresa=empresa).delete()
            for doc in documentos:
                EmpresaDocumentoCCT.objects.get_or_create(empresa=empresa, documento=doc)
        return empresa


class ImportarSindicatosForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo Excel (.xlsx)",
        widget=forms.FileInput(attrs={"class": "form-control", "accept": ".xlsx"}),
    )


class ImportarEmpresasForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo Excel (.xlsx)",
        widget=forms.FileInput(attrs={"class": "form-control", "accept": ".xlsx"}),
    )
