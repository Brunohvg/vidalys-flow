import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from apps.dashboard.global_search import global_search_for_organization
from apps.dashboard.pickups import ready_pickups_for_organization
from apps.dashboard.reports import REPORT_PERIODS, order_report_for_organization
from apps.organizations.selectors import active_organization_for_user
from apps.platform.xlsx import build_xlsx

from .selectors import (
    dashboard_summary,
    fulfillment_attention_for_organization,
    integration_attention_for_organization,
    message_attention_for_organization,
    order_workspace_for_organization,
    payment_attention_for_organization,
    recent_orders_for_organization,
)


def _active_organization_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None or membership is None:
        messages.info(request, "Selecione uma organização ativa para continuar.")
        return None, redirect("organizations:list")
    return organization, None


def _report_parameters(request):
    return {
        "period": request.GET.get("period", "month"),
        "custom_start": request.GET.get("start", ""),
        "custom_end": request.GET.get("end", ""),
    }


def _report_rows(report):
    return [
        (row["day"].isoformat(), row["count"], row["value"] or "0.00")
        for row in report["daily"]
    ]


@login_required
@require_GET
def dashboard_home(request):
    organization, response = _active_organization_or_redirect(request)
    if response:
        return response
    search_query = request.GET.get("q", "").strip()
    integrations = integration_attention_for_organization(organization=organization)
    return render(
        request,
        "dashboard/home.html",
        {
            "organization": organization,
            "summary": dashboard_summary(organization=organization),
            "recent_orders": recent_orders_for_organization(organization=organization),
            "payment_attention": payment_attention_for_organization(organization=organization),
            "fulfillment_attention": fulfillment_attention_for_organization(organization=organization),
            "message_attention": message_attention_for_organization(organization=organization),
            "integration_connections": integrations["connections"],
            "integration_deliveries": integrations["deliveries"],
            "search_query": search_query,
            "search_results": global_search_for_organization(
                organization=organization,
                query=search_query,
            ),
        },
    )


@login_required
@require_GET
def pickup_center(request):
    organization, response = _active_organization_or_redirect(request)
    if response:
        return response
    query = request.GET.get("q", "").strip()
    pickups = ready_pickups_for_organization(organization=organization, query=query)
    return render(
        request,
        "dashboard/pickups.html",
        {
            "organization": organization,
            "query": query,
            "pickups": pickups,
        },
    )


@login_required
@require_GET
def order_report(request):
    organization, response = _active_organization_or_redirect(request)
    if response:
        return response
    report = order_report_for_organization(organization=organization, **_report_parameters(request))
    return render(
        request,
        "dashboard/order_report.html",
        {
            "organization": organization,
            "periods": REPORT_PERIODS,
            "report": report,
        },
    )


@login_required
@require_GET
def order_report_csv(request):
    organization, response = _active_organization_or_redirect(request)
    if response:
        return response
    report = order_report_for_organization(organization=organization, **_report_parameters(request))
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="pedidos-{report["period"]}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(("Data", "Quantidade de pedidos", "Valor dos pedidos"))
    writer.writerows(_report_rows(report))
    return response


@login_required
@require_GET
def order_report_xlsx(request):
    organization, response = _active_organization_or_redirect(request)
    if response:
        return response
    report = order_report_for_organization(organization=organization, **_report_parameters(request))
    payload = build_xlsx(
        headers=("Data", "Quantidade de pedidos", "Valor dos pedidos"),
        rows=_report_rows(report),
    )
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="pedidos-{report["period"]}.xlsx"'
    return response


@login_required
@require_GET
def order_workspace(request, order_id):
    organization, response = _active_organization_or_redirect(request)
    if response:
        return response
    workspace = order_workspace_for_organization(organization=organization, order_id=order_id)
    if workspace is None:
        raise Http404("Pedido não encontrado.")
    return render(request, "dashboard/order_workspace.html", {"organization": organization, **workspace})
