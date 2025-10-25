# Generated manually to add the Farmaco model
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0011_sucursal_imagen"),
    ]

    operations = [
        migrations.CreateModel(
            name="Farmaco",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=150)),
                (
                    "categoria",
                    models.CharField(
                        choices=[
                            ("analgesicos_antiinflamatorios", "Analgésicos y antiinflamatorios"),
                            ("antibioticos", "Antibióticos"),
                            ("antiparasitarios_internos", "Antiparasitarios internos"),
                            ("antiparasitarios_externos", "Antiparasitarios externos"),
                            ("vacunas", "Vacunas"),
                            ("antiemeticos_digestivos", "Antieméticos y digestivos"),
                            ("sueros_soluciones", "Sueros y soluciones"),
                            ("anticonvulsivos", "Anticonvulsivos"),
                            ("corticoides", "Corticoides"),
                            ("anestesicos_sedantes", "Anestésicos y sedantes"),
                            ("antisepticos_topicos", "Antisépticos y tópicos"),
                            ("hormonas_endocrinos", "Hormonas y tratamientos endocrinos"),
                            ("vitaminas_suplementos", "Vitaminas y suplementos nutricionales"),
                            ("oftalmicos_oticos", "Oftálmicos y óticos"),
                            ("productos_dermatologicos", "Productos dermatológicos"),
                            ("eutanasia_emergencias", "Eutanasia y emergencias"),
                        ],
                        max_length=60,
                    ),
                ),
                ("descripcion", models.TextField()),
                ("stock", models.PositiveIntegerField(default=0)),
                ("creado", models.DateTimeField(auto_now_add=True)),
                ("actualizado", models.DateTimeField(auto_now=True)),
                (
                    "sucursal",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="farmacos",
                        to="Core.sucursal",
                    ),
                ),
            ],
            options={
                "ordering": ["sucursal__nombre", "categoria", "nombre"],
                "unique_together": {("sucursal", "nombre")},
            },
        ),
    ]
