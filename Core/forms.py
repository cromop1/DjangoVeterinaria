from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Producto


User = get_user_model()


class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "activo" in self.fields:
            # When creating new staff through the Django admin we want them to
            # appear as disponibles by default so they show up in assignment
            # drop-downs without extra manual steps.
            if not self.instance.pk:
                self.fields["activo"].initial = True
            self.fields["activo"].help_text = (
                "Desmarca esta opción para ocultar al usuario de los listados "
                "operativos sin necesidad de desactivarlo por completo."
            )



class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = [
            "nombre",
            "descripcion",
            "categoria",
            "precio",
            "imagen",
            "telefono_contacto",
            "disponible",
        ]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].widget.attrs.update({"class": "form-control"})
        self.fields["categoria"].widget.attrs.update({"class": "form-select"})
        self.fields["precio"].widget.attrs.update({"class": "form-control", "step": "0.01", "min": "0"})
        self.fields["imagen"].widget.attrs.update({"class": "form-control"})
        self.fields["telefono_contacto"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Ej: +56 9 1234 5678",
            }
        )
        self.fields["disponible"].widget.attrs.update({"class": "form-check-input"})


class VacunaRegistroForm(forms.Form):
    paciente_id = forms.IntegerField(widget=forms.HiddenInput)
    vacuna_id = forms.IntegerField(widget=forms.HiddenInput)
    fecha_aplicacion = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control", "max": "9999-12-31"}),
    )
    notas = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "form-control",
                "placeholder": "Observaciones opcionales",
            }
        ),
    )

    def clean_fecha_aplicacion(self):
        fecha = self.cleaned_data.get("fecha_aplicacion")
        if fecha and fecha > timezone.localdate():
            raise forms.ValidationError(
                "La fecha de aplicación no puede ser posterior a hoy."
            )
        return fecha
