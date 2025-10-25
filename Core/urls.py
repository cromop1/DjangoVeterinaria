from django.urls import path
from . import views

urlpatterns = [
    # ----------------------------
    # LOGIN / LOGOUT / REGISTRO
    # ----------------------------
    path('', views.landing, name='landing'),
    path('contacto/', views.contacto, name='contacto'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registro/', views.registro_propietario, name='registro_propietario'),

    # ----------------------------
    # DASHBOARD
    # ----------------------------
    path('dashboard/', views.dashboard, name='dashboard'),

    # ----------------------------
    # USUARIOS Y PACIENTES (ADMIN / ADMIN_OP)
    # ----------------------------
    path('usuarios/', views.listar_usuarios, name='listar_usuarios'),
    path('pacientes/', views.listar_pacientes, name='listar_pacientes'),

    # ----------------------------
    # MASCOTAS (Propietario)
    # ----------------------------
    path('mis-mascotas/', views.mis_mascotas, name='mis_mascotas'),
    path('calendario-vacunas/', views.calendario_vacunas, name='calendario_vacunas'),
    path('mis-mascotas/registrar/', views.registrar_mascota, name='registrar_mascota'),
    path('mascota/<int:paciente_id>/', views.detalle_mascota, name='detalle_mascota'),

    # ----------------------------
    # TIENDA
    # ----------------------------
    path('tienda/', views.tienda, name='tienda'),
    path('tienda/<int:producto_id>/', views.detalle_producto, name='detalle_producto'),
    path('administrador/productos/', views.admin_productos_list, name='admin_productos_list'),
    path('administrador/productos/nuevo/', views.admin_producto_crear, name='admin_producto_crear'),
    path('administrador/productos/<int:producto_id>/editar/', views.admin_producto_editar, name='admin_producto_editar'),

    # ----------------------------
    # CITAS
    # ----------------------------
    path('mis-citas/', views.mis_citas, name='mis_citas'),
    path('agendar-cita/', views.agendar_cita, name='agendar_cita'),
    path('agendar-cita/<int:paciente_id>/', views.agendar_cita, name='agendar_cita_paciente'),

    # ----------------------------
    # HISTORIAL MÉDICO (VET)
    # ----------------------------
    path('registrar-historial/<int:paciente_id>/', views.registrar_historial, name='registrar_historial'),

    # ADMIN - citas
    path('administrador/citas/', views.listar_citas_admin, name='listar_citas_admin'),
    path('administrador/citas/pendientes/', views.asignar_veterinario_citas, name='asignar_veterinario_citas'),
    path('cita/<int:cita_id>/asignar-vet/', views.asignar_veterinario_cita, name='asignar_veterinario_cita'),
    path('atender_cita/<int:cita_id>/', views.atender_cita, name='atender_cita'),
    path('mis_historiales/', views.mis_historiales, name='mis_historiales'),

    path('cita/<int:cita_id>/', views.detalle_cita, name='detalle_cita'),
    path('agendar_cita_admin/', views.agendar_cita_admin, name='agendar_cita_admin'),
    path('crear_propietario_admin/', views.crear_propietario_admin, name='crear_propietario_admin'),
    path('crear_mascota_admin/', views.crear_mascota_admin, name='crear_mascota_admin'),
    path('buscar_propietarios/', views.buscar_propietarios, name='buscar_propietarios'),
    path('propietario/<int:propietario_id>/', views.detalle_propietario, name='detalle_propietario'),
    path('asignar_veterinario/', views.gestionar_veterinarios, name="gestionar_veterinarios"),
    path("dashboard/veterinarios/", views.dashboard_veterinarios, name="dashboard_veterinarios"),
    path(
        "dashboard/veterinarios/indicadores/",
        views.dashboard_veterinarios_indicadores,
        name="dashboard_veterinarios_indicadores",
    ),
    path('vet/historial-medico/', views.historial_medico_vet, name='historial_medico_vet'),
    path('vet/historial-medico/<int:historial_id>/', views.detalle_historial, name='detalle_historial'),
    

]
