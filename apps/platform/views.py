from django.http import JsonResponse

from apps.platform.health import readiness_report


def liveness(request):
    return JsonResponse({"status": "ok"})


def readiness(request):
    healthy, checks = readiness_report()
    return JsonResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks},
        status=200 if healthy else 503,
    )
