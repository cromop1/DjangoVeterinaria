from django.db import migrations

VACCINE_DATA = [
    {
        "especie": "canino",
        "nombre": "Parvovirus (CPV)",
        "edad_recomendada": 6,
        "unidad_tiempo": "semanas",
        "orden": 10,
        "refuerzo": "Refuerzos a las 9 y 12 semanas",
        "descripcion": "Primera inmunización contra parvovirus canino para cachorros.",
    },
    {
        "especie": "canino",
        "nombre": "Moquillo (CDV)",
        "edad_recomendada": 6,
        "unidad_tiempo": "semanas",
        "orden": 20,
        "refuerzo": "Refuerzos a las 9 y 12 semanas",
        "descripcion": "Protección temprana frente al virus del moquillo canino.",
    },
    {
        "especie": "canino",
        "nombre": "Hepatitis infecciosa (CAV-1)",
        "edad_recomendada": 8,
        "unidad_tiempo": "semanas",
        "orden": 30,
        "refuerzo": "Refuerzo al mes y luego anual",
        "descripcion": "Vacuna combinada contra adenovirus y enfermedades hepáticas virales.",
    },
    {
        "especie": "canino",
        "nombre": "Leptospirosis",
        "edad_recomendada": 12,
        "unidad_tiempo": "semanas",
        "orden": 40,
        "refuerzo": "Refuerzo a las 16 semanas y luego anual",
        "descripcion": "Previene infecciones por leptospira en zonas urbanas y rurales.",
    },
    {
        "especie": "canino",
        "nombre": "Rabia",
        "edad_recomendada": 16,
        "unidad_tiempo": "semanas",
        "orden": 50,
        "refuerzo": "Refuerzo anual obligatorio",
        "descripcion": "Vacunación obligatoria para prevenir la rabia canina.",
    },
    {
        "especie": "canino",
        "nombre": "Bordetella (Tos de las perreras)",
        "edad_recomendada": 18,
        "unidad_tiempo": "semanas",
        "orden": 60,
        "refuerzo": "Refuerzo anual según riesgo",
        "descripcion": "Recomendada para perros con contacto frecuente con otros animales.",
    },
    {
        "especie": "felino",
        "nombre": "Triple Felina (FVRCP)",
        "edad_recomendada": 8,
        "unidad_tiempo": "semanas",
        "orden": 10,
        "refuerzo": "Refuerzos cada 3-4 semanas hasta las 16 semanas",
        "descripcion": "Cubre rinotraqueítis, calicivirus y panleucopenia felina.",
    },
    {
        "especie": "felino",
        "nombre": "Leucemia Felina (FeLV)",
        "edad_recomendada": 12,
        "unidad_tiempo": "semanas",
        "orden": 20,
        "refuerzo": "Segunda dosis a las 16 semanas y luego anual",
        "descripcion": "Recomendada para gatos con acceso al exterior o en colonias.",
    },
    {
        "especie": "felino",
        "nombre": "Rabia",
        "edad_recomendada": 16,
        "unidad_tiempo": "semanas",
        "orden": 30,
        "refuerzo": "Refuerzo anual según normativa local",
        "descripcion": "Protección frente a la rabia felina y cumplimiento legal.",
    },
    {
        "especie": "felino",
        "nombre": "Bordetella Bronchiseptica",
        "edad_recomendada": 16,
        "unidad_tiempo": "semanas",
        "orden": 40,
        "refuerzo": "Anual en gatos de riesgo",
        "descripcion": "Recomendada para gatos que conviven en refugios o pensiones.",
    },
]


def seed_vaccines(apps, schema_editor):
    Vacuna = apps.get_model("Core", "VacunaRecomendada")

    for data in VACCINE_DATA:
        Vacuna.objects.get_or_create(
            especie=data["especie"],
            nombre=data["nombre"],
            defaults={
                "edad_recomendada": data["edad_recomendada"],
                "unidad_tiempo": data["unidad_tiempo"],
                "orden": data["orden"],
                "refuerzo": data.get("refuerzo", ""),
                "descripcion": data.get("descripcion", ""),
            },
        )


def unseed_vaccines(apps, schema_editor):
    Vacuna = apps.get_model("Core", "VacunaRecomendada")
    for data in VACCINE_DATA:
        Vacuna.objects.filter(especie=data["especie"], nombre=data["nombre"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0004_vacunas"),
    ]

    operations = [
        migrations.RunPython(seed_vaccines, reverse_code=unseed_vaccines),
    ]
